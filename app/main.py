from fastapi import FastAPI, Request, HTTPException
import json, re
from .config import settings
from .payments import _choose_api_key, cents_from_str, create_payment
from .monday import get_item_columns, set_link_in_column, set_status
from .evoliz import create_quote, extract_public_link

app = FastAPI(title="Energyz Payment Automation", version="2.1")

@app.get("/")
def root():
    return {"status": "ok", "message": "Energyz Payment Automation is live 🚀"}

def _clean_number_text(s: str) -> str:
    if not s:
        return "0"
    s = s.replace("\u202f", "").replace(" ", "").replace("€", "").strip().replace(",", ".")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    return m.group(0) if m else "0"

@app.post("/quote/from_monday")
async def quote_from_monday(request: Request):
    try:
        payload = await request.json()
        event = payload.get("event", {})
        item_id = event.get("pulseId") or event.get("itemId")
        column_id = event.get("columnId", "")

        if not item_id:
            raise HTTPException(status_code=400, detail="Item ID manquant.")

        # Détections
        formula_columns = json.loads(settings.FORMULA_COLUMN_IDS_JSON)
        link_columns = json.loads(settings.LINK_COLUMN_IDS_JSON)
        status_after = json.loads(settings.STATUS_AFTER_PAY_JSON)
        acompte_num = next((k for k, v in formula_columns.items() if v == column_id), None)
        is_create_quote = (column_id == settings.CREATE_QUOTE_STATUS_COLUMN_ID)

        if not acompte_num and not is_create_quote:
            raise HTTPException(status_code=400, detail=f"Colonne déclenchante inconnue: {column_id}")

        # Lecture colonnes (on veut aussi le RAW de l'adresse)
        wanted = [
            settings.EMAIL_COLUMN_ID,
            settings.ADDRESS_COLUMN_ID,
            settings.DESCRIPTION_COLUMN_ID,
            settings.IBAN_FORMULA_COLUMN_ID,
            settings.QUOTE_AMOUNT_FORMULA_ID,  # Total HT
            settings.VAT_RATE_COLUMN_ID,
            settings.TOTAL_HT_COLUMN_ID,
            settings.TOTAL_TTC_COLUMN_ID
        ]
        cols = get_item_columns(item_id, wanted)
        # Récup RAW adresse si présent
        address_raw_json = cols.get(f"{settings.ADDRESS_COLUMN_ID}__raw")
        try:
            address_raw = json.loads(address_raw_json) if address_raw_json else None
        except Exception:
            address_raw = None

        name        = cols.get("name", "Client Energyz")
        email       = cols.get(settings.EMAIL_COLUMN_ID, "")
        address_txt = cols.get(settings.ADDRESS_COLUMN_ID, "")
        description = cols.get(settings.DESCRIPTION_COLUMN_ID, "")
        iban        = cols.get(settings.IBAN_FORMULA_COLUMN_ID, "")
        total_ht    = cols.get(settings.TOTAL_HT_COLUMN_ID) or cols.get(settings.QUOTE_AMOUNT_FORMULA_ID) or "0"
        vat_rate    = cols.get(settings.VAT_RATE_COLUMN_ID, "") or "20"

        # ===== ACOMPTES =====
        if acompte_num:
            api_key = _choose_api_key(iban)
            amount_cents = cents_from_str(total_ht)
            if acompte_num == "2":
                amount_cents //= 2
            metadata = {"item_id": item_id, "acompte": acompte_num}
            payment_url = create_payment(api_key, amount_cents, email, address_txt, description, metadata)
            set_link_in_column(item_id, link_columns[acompte_num], payment_url, f"Payer acompte {acompte_num}")
            set_status(item_id, settings.STATUS_COLUMN_ID, status_after[acompte_num])
            return {"status": "ok", "type": "acompte", "acompte": acompte_num, "payment_url": payment_url}

        # ===== DEVIS EVOLIZ =====
        unit_price_ht = float(_clean_number_text(total_ht))
        vr = float(_clean_number_text(vat_rate)) if str(vat_rate).strip() != "" else 20.0
        label = name or description or "Devis"

        quote = create_quote(
            label=label,
            description=description,
            unit_price_ht=unit_price_ht,
            vat_rate=vr,
            recipient_name=name,
            recipient_email=email,
            recipient_address_json=address_raw   # <-- adresse structurée (street, town, postcode, iso2)
        )
        public_url = extract_public_link(quote) or settings.EVOLIZ_BASE_URL
        set_link_in_column(item_id, settings.QUOTE_LINK_COLUMN_ID, public_url, "Devis Evoliz")

        return {"status": "ok", "type": "devis", "public_url": public_url, "evoliz": quote}

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Evoliz quote error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
