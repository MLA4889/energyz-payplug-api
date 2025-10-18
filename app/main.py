# src/app/main.py
import json
import re
from fastapi import FastAPI, Request, HTTPException

from .config import settings
from .payments import _choose_api_key, cents_from_str, create_payment
from .monday import get_item_columns, set_link_in_column, set_status

# Evoliz neutre par défaut
ENABLE_EVOLIZ = bool(getattr(settings, "ENABLE_EVOLIZ", False))
HAVE_EVOLIZ = False
if ENABLE_EVOLIZ:
    try:
        from .evoliz import (
            create_quote,
            extract_identifiers,
            get_or_create_public_link,
            build_app_quote_url,
            download_quote_pdf,
        )
        HAVE_EVOLIZ = True
    except Exception:
        HAVE_EVOLIZ = False

app = FastAPI(title="Energyz Payment Automation (stable)", version="3.2.0")


@app.get("/")
def root():
    return {"status": "ok", "message": "Energyz Payment Automation is live 🚀"}


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
    # 1) text
    txt = cols.get(fid, "")
    v = _num(txt, None if fallback is None else fallback)
    if v and v > 0:
        return v
    # 2) value JSON
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


def _detect_acompte_num(event: dict, formula_columns: dict[str, str]) -> str | None:
    """
    Retourne "1" ou "2" si on détecte l'acompte demandé.
    - Cas réel Monday: colonneId == "status" avec value.label.text = "Générer acompte 1/2"
    - Fallback: si columnId == id d'une colonne formula connue (ancien mode)
    """
    col_id = event.get("columnId", "") or ""
    # 1) Détection par libellé du statut
    value = event.get("value")
    val_json = None
    if isinstance(value, dict):
        val_json = value
    elif isinstance(value, str):
        try:
            val_json = json.loads(value)
        except Exception:
            val_json = None
    label_text = ""
    if isinstance(val_json, dict):
        label = val_json.get("label") or {}
        label_text = (label.get("text") or "").lower().strip()
    if "générer acompte 1" in label_text:
        return "1"
    if "générer acompte 2" in label_text:
        return "2"

    # 2) Fallback: si la colonne déclenchante EST une des colonnes formula
    for k, fid in formula_columns.items():
        if fid == col_id:
            return k

    return None


@app.post("/quote/from_monday")
async def quote_from_monday(request: Request):
    try:
        payload = await request.json()
        event = payload.get("event", {})
        item_id = event.get("pulseId") or event.get("itemId")
        if not item_id:
            raise HTTPException(status_code=400, detail="Item ID manquant.")

        formula_columns = json.loads(settings.FORMULA_COLUMN_IDS_JSON)   # {"1":"formula_ac1","2":"formula_ac2"}
        link_columns = json.loads(settings.LINK_COLUMN_IDS_JSON)         # {"1":"link_ac1","2":"link_ac2"}
        status_after = json.loads(settings.STATUS_AFTER_PAY_JSON)        # {"1":"Payé acompte 1","2":"Payé acompte 2"}

        acompte_num = _detect_acompte_num(event, formula_columns)
        is_quote_trigger = bool(getattr(settings, "CREATE_QUOTE_STATUS_COLUMN_ID", None)) and \
            (event.get("columnId") == settings.CREATE_QUOTE_STATUS_COLUMN_ID)

        # Colonnes à lire
        wanted = [
            settings.EMAIL_COLUMN_ID,
            settings.ADDRESS_COLUMN_ID,
            settings.DESCRIPTION_COLUMN_ID,
            settings.IBAN_FORMULA_COLUMN_ID,
            settings.QUOTE_AMOUNT_FORMULA_ID,
        ]
        for opt in (getattr(settings, "VAT_RATE_COLUMN_ID", None),
                    getattr(settings, "TOTAL_HT_COLUMN_ID", None),
                    getattr(settings, "TOTAL_TTC_COLUMN_ID", None)):
            if opt:
                wanted.append(opt)

        cols = get_item_columns(item_id, wanted)

        # Données de base
        name = cols.get("name", "")
        email = cols.get(settings.EMAIL_COLUMN_ID, "")
        address_txt = cols.get(settings.ADDRESS_COLUMN_ID, "")
        description = cols.get(settings.DESCRIPTION_COLUMN_ID, "") or name

        # ====== Paiements acompte 1/2 ======
        if acompte_num in ("1", "2"):
            iban = cols.get(settings.IBAN_FORMULA_COLUMN_ID, "")
            api_key = _choose_api_key(iban)

            amount_formula_id = formula_columns.get(acompte_num)
            base_total_txt = cols.get(getattr(settings, "TOTAL_HT_COLUMN_ID", None) or settings.QUOTE_AMOUNT_FORMULA_ID, "0")
            base_total = _num(base_total_txt, 0.0)

            if acompte_num == "1":
                amount = _from_formula(cols, amount_formula_id, fallback=base_total)  # 100% si formule vide
            else:
                amount = _from_formula(cols, amount_formula_id, fallback=(base_total / 2.0 if base_total else 0.0))  # 50%

            amount_cents = cents_from_str(str(amount))
            if amount_cents <= 0:
                raise HTTPException(status_code=400, detail=f"Montant invalide pour l'acompte {acompte_num}")

            pay_url = create_payment(
                api_key,
                amount_cents,
                email,
                address_txt,
                description,
                {"item_id": item_id, "acompte": acompte_num},
            )

            set_link_in_column(item_id, link_columns[acompte_num], pay_url, f"Payer acompte {acompte_num}")
            set_status(item_id, settings.STATUS_COLUMN_ID, status_after[acompte_num])

            return {"status": "ok", "type": "acompte", "acompte": acompte_num, "amount": amount, "payment_url": pay_url}

        # ====== Devis Evoliz (optionnel) ======
        if is_quote_trigger and HAVE_EVOLIZ:
            try:
                total_ht = cols.get(getattr(settings, "TOTAL_HT_COLUMN_ID", None) or settings.QUOTE_AMOUNT_FORMULA_ID, "0")
                vat_rate = cols.get(getattr(settings, "VAT_RATE_COLUMN_ID", None) or "", "") or "20"
                unit_price_ht = _num(total_ht, 0.0)
                vr = _num(vat_rate, 20.0)

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
                url_to_set = public_url or deep_link or (getattr(settings, "EVOLIZ_BASE_URL", None) or "https://www.evoliz.io")

                if getattr(settings, "QUOTE_LINK_COLUMN_ID", None):
                    set_link_in_column(item_id, settings.QUOTE_LINK_COLUMN_ID, url_to_set, link_text)

                if not public_url and getattr(settings, "QUOTE_FILES_COLUMN_ID", None):
                    try:
                        pdf_bytes, filename = download_quote_pdf(qid)
                        from .monday import upload_file_to_column
                        upload_file_to_column(item_id, settings.QUOTE_FILES_COLUMN_ID, filename, pdf_bytes)
                    except Exception:
                        pass

                return {"status": "ok", "type": "devis", "quote_id": qid, "link_used": url_to_set}
            except Exception as e:
                return {"status": "ok", "type": "devis", "warning": str(e)}

        return {"status": "ignored", "detail": f"Colonne {event.get('columnId')} non gérée."}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== Test PayPlug sans Monday =====
@app.post("/pay/acompte/{n}")
def pay_acompte_test(n: int):
    try:
        test_iban = "FR76 1695 8000 0130 5670 5696 366"
        api_key = _choose_api_key(test_iban)
        amount_cents = cents_from_str("1250") // (2 if n == 2 else 1)
        url = create_payment(
            api_key,
            amount_cents,
            "testo@test.fr",
            "Adresse de test",
            f"Test acompte {n}",
            {"acompte": str(n), "mode": "test-endpoint"},
        )
        return {"status": "ok", "acompte": n, "payment_url": url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
