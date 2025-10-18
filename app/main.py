from fastapi import FastAPI, Request, HTTPException
from .payments import _choose_api_key, cents_from_str, create_payment
from .monday import get_item_columns, set_link_in_column, set_status
from .config import settings
import json
import re

app = FastAPI(title="Energyz PayPlug API", version="1.1")

def _clean_amount_text(s: str) -> str:
    if not s:
        return "0"
    s = s.replace("\u202f", "").replace(" ", "").replace("€", "").strip()
    s = s.replace(",", ".")
    # Prend la première occurrence nombre décimal
    m = re.search(r"[-+]?\d*\.?\d+", s)
    return m.group(0) if m else "0"

@app.get("/")
def root():
    return {"status": "ok", "message": "Energyz PayPlug API is live 🚀"}

@app.post("/quote/from_monday")
async def quote_from_monday(request: Request):
    try:
        payload = await request.json()
        event = payload.get("event", {}) or {}
        item_id = event.get("pulseId") or event.get("itemId")
        if not item_id:
            raise HTTPException(status_code=400, detail="Item ID manquant dans le webhook")

        # 1) Déterminer si on a cliqué Acompte 1 ou 2 sur la colonne TRIGGER
        trigger_col = event.get("columnId")
        trigger_status_col = getattr(settings, "TRIGGER_STATUS_COLUMN_ID", "status")
        trigger_labels = json.loads(getattr(settings, "TRIGGER_LABELS_JSON", '{"1":"Acompte 1","2":"Acompte 2"}'))

        acompte_num = None
        if trigger_col == trigger_status_col:
            # Monday envoie souvent la value JSON sous event["value"]
            raw_value = event.get("value")
            # raw_value peut être un str JSON -> on le parse
            try:
                value_json = json.loads(raw_value) if isinstance(raw_value, str) else (raw_value or {})
            except Exception:
                value_json = {}
            current_label = (value_json.get("label") or value_json.get("value") or "").strip()
            for k, label in trigger_labels.items():
                if current_label == label:
                    acompte_num = k

        if acompte_num not in ("1", "2"):
            raise HTTPException(status_code=400, detail=f"Webhook non reconnu (colonne:{trigger_col}, label actuel incompatible)")

        # 2) Lire les colonnes nécessaires
        formula_cols = json.loads(settings.FORMULA_COLUMN_IDS_JSON)  # {"1":"formula_x","2":"formula_y"}
        link_columns = json.loads(settings.LINK_COLUMN_IDS_JSON)     # {"1":"link_x","2":"link_y"}

        needed_cols = [
            settings.EMAIL_COLUMN_ID,
            settings.ADDRESS_COLUMN_ID,
            settings.DESCRIPTION_COLUMN_ID,
            settings.IBAN_FORMULA_COLUMN_ID,
            settings.QUOTE_AMOUNT_FORMULA_ID,    # Montant total HT
            formula_cols[acompte_num],           # Montant acompte 1 ou 2 (formula)
            getattr(settings, "BUSINESS_STATUS_COLUMN_ID", "color_mkwnxf1h")  # pour fallback IBAN
        ]

        cols = get_item_columns(item_id, needed_cols)

        email = cols.get(settings.EMAIL_COLUMN_ID, "")
        address = cols.get(settings.ADDRESS_COLUMN_ID, "")
        description = cols.get(settings.DESCRIPTION_COLUMN_ID, "")
        iban = cols.get(settings.IBAN_FORMULA_COLUMN_ID, "")

        # Montant acompte via formula dédiée
        acompte_formula_val = cols.get(formula_cols[acompte_num], "")
        acompte_amount_txt = _clean_amount_text(acompte_formula_val)

        # Fallback montant : si formula vide/0 -> on prend Montant total HT / 2 pour acompte
        if float(acompte_amount_txt or "0") <= 0:
            total_ht_txt = _clean_amount_text(cols.get(settings.QUOTE_AMOUNT_FORMULA_ID, "0"))
            if float(total_ht_txt) > 0:
                acompte_amount_txt = str(float(total_ht_txt) / 2.0)
            else:
                raise HTTPException(status_code=400, detail="Montant introuvable (formula acompte et total HT vides)")

        amount_cents = cents_from_str(acompte_amount_txt)

        # Fallback IBAN basé sur Business Line / Société
        if not iban:
            iban_by_status = json.loads(getattr(settings, "IBAN_BY_STATUS_JSON", "{}"))
            business_status_label = cols.get(getattr(settings, "BUSINESS_STATUS_COLUMN_ID", "color_mkwnxf1h"), "")
            if business_status_label and business_status_label in iban_by_status:
                iban = iban_by_status[business_status_label]

        if not iban:
            raise HTTPException(status_code=400, detail="IBAN introuvable (formula vide et aucun fallback Business Line)")

        # 3) Clé PayPlug par IBAN
        api_key = _choose_api_key(iban)
        if not api_key:
            raise HTTPException(status_code=400, detail=f"Aucune clé PayPlug mappée pour IBAN: {iban}")

        # 4) Créer le paiement
        metadata = {"item_id": str(item_id), "acompte": acompte_num}
        payment_url = create_payment(api_key, amount_cents, email, address, description, metadata)

        # 5) Écrire le lien + mettre le statut paiement
        set_link_in_column(item_id, link_columns[acompte_num], payment_url, f"Payer acompte {acompte_num}")
        status_after = json.loads(settings.STATUS_AFTER_PAY_JSON)
        set_status(item_id, settings.STATUS_COLUMN_ID, status_after[acompte_num])

        return {"status": "ok", "item_id": item_id, "acompte": acompte_num, "amount_cents": amount_cents, "payment_url": payment_url}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur webhook Monday : {e}")
