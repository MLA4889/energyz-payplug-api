# src/app/main.py
import json
import re
from fastapi import FastAPI, Request, HTTPException

from .config import settings
from .payments import _choose_api_key, cents_from_str, create_payment
from .monday import get_item_columns, set_link_in_column, set_status

# Evoliz désactivé par défaut (et inoffensif)
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

app = FastAPI(title="Energyz Payment Automation (stable)", version="3.1.0")


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
    """
    Lit un montant d'une colonne formula Monday.
    Essaye .text, puis .value(JSON)->text/value/label/result, sinon fallback.
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
    """
    Webhook Monday :
    - si colonne = FORMULA_COLUMN_IDS_JSON['1'|'2'] → génère lien PayPlug, met le statut.
    - si colonne = CREATE_QUOTE_STATUS_COLUMN_ID et Evoliz activé → essaie de créer un devis (n'influence JAMAIS les paiements).
    """
    try:
        payload = await request.json()
        event = payload.get("event", {})
        item_id = event.get("pulseId") or event.get("itemId")
        column_id = event.get("columnId", "")

        if not item_id:
            raise HTTPException(status_code=400, detail="Item ID manquant.")

        formula_columns = json.loads(settings.FORMULA_COLUMN_IDS_JSON)   # {"1":"formula_xxx","2":"formula_yyy"}
        link_columns = json.loads(settings.LINK_COLUMN_IDS_JSON)         # {"1":"link_xxx","2":"link_yyy"}
        status_after = json.loads(settings.STATUS_AFTER_PAY_JSON)        # {"1":"Payé acompte 1","2":"Payé acompte 2"}

        acompte_num = next((k for k, v in formula_columns.items() if v == column_id), None)
        is_quote_trigger = bool(getattr(settings, "CREATE_QUOTE_STATUS_COLUMN_ID", None)) and \
            (column_id == settings.CREATE_QUOTE_STATUS_COLUMN_ID)

        # Colonnes nécessaires
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
        address_txt = cols.get(settings.ADDRESS_COLUMN_ID, "")  # on prend le texte visible dans Monday
        description = cols.get(settings.DESCRIPTION_COLUMN_ID, "") or name

        # ====== Paiements acompte 1/2 ======
        if acompte_num:
            iban = cols.get(settings.IBAN_FORMULA_COLUMN_ID, "")
            api_key = _choose_api_key(iban)

            amount_formula_id = formula_columns.get(acompte_num)
            base_total_txt = cols.get(getattr(settings, "TOTAL_HT_COLUMN_ID", None) or settings.QUOTE_AMOUNT_FORMULA_ID, "0")
            base_total = _num(base_total_txt, 0.0)

            if acompte_num == "1":
                amount = _from_formula(cols, amount_formula_id, fallback=base_total)  # acompte 1 = formule sinon 100% HT
            else:
                amount = _from_formula(cols, amount_formula_id, fallback=(base_total / 2.0 if base_total else 0.0))  # acompte 2

            amount_cents = cents_from_str(str(amount))
            if amount_cents <= 0:
                raise HTTPException(status_code=400, detail=f"Montant invalide pour l'acompte {acompte_num}")

            metadata = {"item_id": item_id, "acompte": acompte_num}
            pay_url = create_payment(api_key, amount_cents, email, address_txt, description, metadata)

            set_link_in_column(item_id, link_columns[acompte_num], pay_url, f"Payer acompte {acompte_num}")
            set_status(item_id, settings.STATUS_COLUMN_ID, status_after[acompte_num])

            return {"status": "ok", "type": "acompte", "acompte": acompte_num, "amount": amount, "payment_url": pay_url}

        # ====== Devis Evoliz (optionnel, n'influence jamais les paiements) ======
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

                # essai d'upload PDF si pas de lien public et colonne fichiers configurée
                if not public_url and getattr(settings, "QUOTE_FILES_COLUMN_ID", None):
                    try:
                        pdf_bytes, filename = download_quote_pdf(qid)
                        from .monday import upload_file_to_column
                        upload_file_to_column(item_id, settings.QUOTE_FILES_COLUMN_ID, filename, pdf_bytes)
                    except Exception:
                        pass

                return {"status": "ok", "type": "devis", "quote_id": qid, "link_used": url_to_set}
            except Exception as e:
                # ne bloque pas le flux
                return {"status": "ok", "type": "devis", "warning": str(e)}

        return {"status": "ignored", "detail": f"Colonne {column_id} non gérée."}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== Endpoint de TEST PayPlug (remis) =====
@app.post("/pay/acompte/{n}")
def pay_acompte_test(n: int):
    """
    Génère un lien PayPlug sans Monday (simple test).
    Montant : 1250€ (ou 625€ si n==2). Adresse/email/description factices.
    Choix de clé : on prend l'IBAN de ton env (ou la 1ère clé).
    """
    try:
        # essaie de prendre un IBAN connu; sinon le _choose_api_key() prendra la 1ère clé du JSON
        test_iban = "FR76 1695 8000 0130 5670 5696 366"
        api_key = _choose_api_key(test_iban)
        amount_cents = cents_from_str("1250") // (2 if n == 2 else 1)
        url = create_payment(
            api_key,
            amount_cents,
            "testo@test.fr",
            "Adresse de test",
            f"Test acompte {n}",
            {"acompte": str(n), "mode": "test-endpoint"}
        )
        return {"status": "ok", "acompte": n, "payment_url": url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
