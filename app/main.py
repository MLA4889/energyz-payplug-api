import json
import re
from fastapi import FastAPI, Request, HTTPException

from .config import settings
from .payments import _choose_api_key, cents_from_str, create_payment
from .monday import get_item_columns, set_link_in_column, set_status

# Evoliz est optionnel : on ne casse JAMAIS les acomptes
ENABLE_EVOLIZ = bool(settings.ENABLE_EVOLIZ)

if ENABLE_EVOLIZ:
    # imports "souples" pour éviter tout crash si non configuré
    try:
        from .evoliz import create_quote, extract_identifiers, get_or_create_public_link, build_app_quote_url, download_quote_pdf
        from .monday import upload_file_to_column  # si tu veux attacher les PDF
        HAVE_EVOLIZ = True
    except Exception:
        HAVE_EVOLIZ = False
else:
    HAVE_EVOLIZ = False

app = FastAPI(title="Energyz Payment Automation (stable)", version="3.0.0")


@app.get("/")
def root():
    return {"status": "ok", "message": "Energyz Payment Automation is live 🚀 (paiements stables)"}


def _num(text: str, default: float = 0.0) -> float:
    if not text:
        return default
    s = text.replace("€", "").replace("\u202f", "").replace(" ", "").replace(",", ".")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    try:
        return float(m.group(0)) if m else default
    except Exception:
        return default


def _from_formula(cols: dict, fid: str, fallback: float | None = None) -> float:
    """
    Essaie de lire le montant depuis une colonne formula:
    - text si numérique
    - sinon value (JSON) -> tente text/value/label/result
    - sinon fallback
    """
    txt = cols.get(fid, "")
    v = _num(txt, None if fallback is None else fallback)
    if v and v > 0:
        return v
    raw = cols.get(f"{fid}__raw", "")
    if raw:
        try:
            j = json.loads(raw)
            for key in ("text", "value", "label", "result"):
                val = j.get(key) if isinstance(j, dict) else None
                if isinstance(val, (int, float)) and val > 0:
                    return float(val)
                if isinstance(val, str):
                    vv = _num(val, None if fallback is None else fallback)
                    if vv and vv > 0:
                        return vv
        except Exception:
            pass
    return fallback if fallback is not None else 0.0


@app.post("/quote/from_monday")
async def quote_from_monday(request: Request):
    try:
        payload = await request.json()
        event = payload.get("event", {})
        item_id = event.get("pulseId") or event.get("itemId")
        column_id = event.get("columnId", "")

        if not item_id:
            raise HTTPException(status_code=400, detail="Item ID manquant.")

        formula_columns = json.loads(settings.FORMULA_COLUMN_IDS_JSON)
        link_columns = json.loads(settings.LINK_COLUMN_IDS_JSON)
        status_after = json.loads(settings.STATUS_AFTER_PAY_JSON)

        acompte_num = next((k for k, v in formula_columns.items() if v == column_id), None)
        is_quote_trigger = bool(settings.CREATE_QUOTE_STATUS_COLUMN_ID) and (column_id == settings.CREATE_QUOTE_STATUS_COLUMN_ID)

        wanted = [
            settings.EMAIL_COLUMN_ID,
            settings.ADDRESS_COLUMN_ID,
            settings.DESCRIPTION_COLUMN_ID,
            settings.IBAN_FORMULA_COLUMN_ID,
            settings.QUOTE_AMOUNT_FORMULA_ID,
        ]
        # champs devis optionnels
        for opt in (settings.VAT_RATE_COLUMN_ID, settings.TOTAL_HT_COLUMN_ID, settings.TOTAL_TTC_COLUMN_ID):
            if opt:
                wanted.append(opt)

        cols = get_item_columns(item_id, wanted)

        # Données communes
        name = cols.get("name", "")
        email = cols.get(settings.EMAIL_COLUMN_ID, "")
        address_txt = cols.get(settings.ADDRESS_COLUMN_ID, "")  # on prend le TEXT affiché dans Monday
        description = cols.get(settings.DESCRIPTION_COLUMN_ID, "") or name

        # ======== 1) Paiements (acompte 1/2) – priorité absolue ========
        if acompte_num:
            iban = cols.get(settings.IBAN_FORMULA_COLUMN_ID, "")
            api_key = _choose_api_key(iban)

            # on privilégie la colonne formula spécifique à l'acompte si elle retourne un nombre
            amount_formula_id = formula_columns.get(acompte_num)
            total_ht_txt = cols.get(settings.TOTAL_HT_COLUMN_ID or settings.QUOTE_AMOUNT_FORMULA_ID, "0")
            base_total = _num(total_ht_txt, 0.0)

            if acompte_num == "1":
                amount = _from_formula(cols, amount_formula_id, fallback=base_total)  # 1er acompte : formule ou 100% HT
            else:
                # acompte 2 : formule sinon 50% du total HT
                fallback = base_total / 2.0 if base_total else 0.0
                amount = _from_formula(cols, amount_formula_id, fallback=fallback)

            amount_cents = cents_from_str(str(amount))
            metadata = {"item_id": item_id, "acompte": acompte_num}
            url = create_payment(api_key, amount_cents, email, address_txt, description, metadata)

            set_link_in_column(item_id, link_columns[acompte_num], url, f"Payer acompte {acompte_num}")
            set_status(item_id, settings.STATUS_COLUMN_ID, status_after[acompte_num])

            return {"status": "ok", "type": "acompte", "acompte": acompte_num, "amount": amount, "payment_url": url}

        # ======== 2) Devis Evoliz (optionnel et NE BLOQUE PAS) ========
        if is_quote_trigger and HAVE_EVOLIZ:
            try:
                # Calculs
                total_ht = cols.get(settings.TOTAL_HT_COLUMN_ID or settings.QUOTE_AMOUNT_FORMULA_ID, "0")
                vat_rate = cols.get(settings.VAT_RATE_COLUMN_ID, "") or "20"
                unit_price_ht = _num(total_ht, 0.0)
                vr = _num(vat_rate, 20.0)

                # Adresse brute (pour Evoliz seulement si besoin)
                addr_raw = cols.get(f"{settings.ADDRESS_COLUMN_ID}__raw", "")
                try:
                    address_raw = json.loads(addr_raw) if addr_raw else None
                except Exception:
                    address_raw = None

                q = create_quote(
                    label=name or description or "Devis",
                    description=description,
                    unit_price_ht=unit_price_ht,
                    vat_rate=vr,
                    recipient_name=name or "Client",
                    recipient_email=email,
                    recipient_address_json=address_raw,
                )
                qid, qnum = extract_identifiers(q)
                public_url = get_or_create_public_link(qid, recipient_email=email)
                deep_link = build_app_quote_url(qid)

                link_text = "Devis Evoliz"
                if qnum:
                    link_text += f" #{qnum}"
                if qid:
                    link_text += f" (ID:{qid})"

                url_to_set = public_url or deep_link or (settings.EVOLIZ_BASE_URL or "https://www.evoliz.io")
                if settings.QUOTE_LINK_COLUMN_ID:
                    set_link_in_column(item_id, settings.QUOTE_LINK_COLUMN_ID, url_to_set, link_text)

                # Fallback PDF (silencieux si indispo)
                if not public_url and settings.QUOTE_FILES_COLUMN_ID:
                    try:
                        pdf_bytes, filename = download_quote_pdf(qid)
                        from .monday import upload_file_to_column
                        upload_file_to_column(item_id, settings.QUOTE_FILES_COLUMN_ID, filename, pdf_bytes)
                    except Exception:
                        pass

                return {
                    "status": "ok",
                    "type": "devis",
                    "quote_id": qid,
                    "link_used": url_to_set,
                    "public_url": public_url,
                    "deep_link": deep_link,
                }
            except Exception as e:
                # On NE bloque PAS le flux (on renvoie un OK tout de même)
                return {"status": "ok", "type": "devis", "warning": str(e)}

        # Si la colonne ne correspond à rien de gérable
        return {"status": "ignored", "detail": f"Colonne {column_id} non gérée."}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
