from fastapi import FastAPI, Request, HTTPException
import json
from .payments import _choose_api_key, cents_from_str, create_payment
from .monday import get_item_columns, set_link_in_column, set_status
from .config import settings
from .evoliz import create_quote, extract_public_link

app = FastAPI(title="Energyz PayPlug API", version="1.1")

@app.get("/")
def root():
    return {"status": "ok", "message": "Energyz Payment Automation is live 🚀"}

def _safe_float(text_value: str, fallback: float = 0.0) -> float:
    try:
        return float(str(text_value).replace(",", "."))
    except Exception:
        return fallback

@app.post("/quote/from_monday")
async def quote_from_monday(request: Request):
    try:
        payload = await request.json()
        print("[WEBHOOK] payload=", payload)
        event = payload.get("event", {})
        item_id = event.get("pulseId") or event.get("itemId")
        column_id = event.get("columnId", "")

        # ===== Déclencheurs ACOMPTE (identique à ta version) =====
        formula_columns = json.loads(settings.FORMULA_COLUMN_IDS_JSON)
        link_columns = json.loads(settings.LINK_COLUMN_IDS_JSON)
        status_after = json.loads(settings.STATUS_AFTER_PAY_JSON)

        acompte_num = next((k for k, v in formula_columns.items() if v == column_id), None)

        # ===== Déclencheur DEVIS =====
        is_create_quote = (column_id == settings.CREATE_QUOTE_STATUS_COLUMN_ID)

        # Rien à faire ?
        if not acompte_num and not is_create_quote:
            raise HTTPException(status_code=400, detail=f"Colonne déclenchante inconnue: {column_id}")

        # Récup des colonnes utiles
        cols = get_item_columns(item_id, [
            settings.EMAIL_COLUMN_ID,
            settings.ADDRESS_COLUMN_ID,
            settings.DESCRIPTION_COLUMN_ID,
            settings.IBAN_FORMULA_COLUMN_ID,
            settings.QUOTE_AMOUNT_FORMULA_ID,
            settings.VAT_RATE_COLUMN_ID,
            settings.TOTAL_HT_COLUMN_ID,
            settings.TOTAL_TTC_COLUMN_ID
        ])

        email       = cols.get(settings.EMAIL_COLUMN_ID, "")
        address     = cols.get(settings.ADDRESS_COLUMN_ID, "")
        description = cols.get(settings.DESCRIPTION_COLUMN_ID, "")
        iban        = cols.get(settings.IBAN_FORMULA_COLUMN_ID, "")
        amount_ht   = cols.get(settings.QUOTE_AMOUNT_FORMULA_ID, "")  # Montant total HT (utilisé aussi pour acomptes en %)
        vat_rate    = cols.get(settings.VAT_RATE_COLUMN_ID, "") or "20"

        # ====== ACOMPTE 1/2 ======
        if acompte_num:
            api_key = _choose_api_key(iban)
            amount_cents = cents_from_str(amount_ht)
            if acompte_num == "2":
                amount_cents //= 2  # règle existante

            metadata = {"item_id": item_id, "acompte": acompte_num}
            payment_url = create_payment(api_key, amount_cents, email, address, description, metadata)

            set_link_in_column(item_id, link_columns[acompte_num], payment_url, f"Payer acompte {acompte_num}")
            set_status(item_id, settings.STATUS_COLUMN_ID, status_after[acompte_num])

            return {"status": "ok", "type": "acompte", "acompte": acompte_num, "payment_url": payment_url}

        # ====== CREATION DEVIS EVOLIZ ======
        # On privilégie le HT depuis la colonne dédiée ; si vide, on reprend QUOTE_AMOUNT_FORMULA_ID.
        unit_price_ht = _safe_float(cols.get(settings.TOTAL_HT_COLUMN_ID) or amount_ht, 0.0)
        vr = _safe_float(vat_rate, 20.0)

        # label = nom de l’item Monday, description = "Description presta"
        label = cols.get("name", "") or description or "Devis"

        quote = create_quote(label=label, description=description, unit_price_ht=unit_price_ht, vat_rate=vr)
        public_url = extract_public_link(quote) or settings.EVOLIZ_BASE_URL  # secours

        # Dépose le lien dans la colonne “Devis”
        set_link_in_column(item_id, settings.QUOTE_LINK_COLUMN_ID, public_url, "Devis Evoliz")

        return {"status": "ok", "type": "devis", "quote_response": quote, "public_url": public_url}

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Petit endpoint de test manuel PayPlug existant
@app.post("/pay/acompte/{n}")
async def create_acompte_link(n: int):
    try:
        from_iban = "FR76 1695 8000 0130 5670 5696 366"
        api_key = _choose_api_key(from_iban)
        amount_cents = cents_from_str("1250.00") // (2 if n == 2 else 1)
        metadata = {"client": "Jean Dupont", "acompte": str(n)}
        url = create_payment(api_key, amount_cents, "jean@mail.com", "12 rue de Paris", "Installation solaire", metadata)
        return {"status": "ok", "acompte": n, "payment_url": url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
