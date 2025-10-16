from fastapi import FastAPI, HTTPException, Body, Request
from typing import Any
import json as _json
from pydantic import BaseModel

from .config import settings
from .monday import get_item_columns, get_formula_display_value, set_link_in_column, set_status
from .payments import create_payment, cents_from_str, _choose_api_key
from . import evoliz

app = FastAPI(title="ENERGYZ PayPlug API")

@app.get("/")
def root():
    return {"status": "ok", "brand": settings.BRAND_NAME}

@app.get("/health")
def health():
    return {"status": "ok", "service": "energyz-payplug-api"}


# --- Génération de lien PayPlug (identique version stable) ---
@app.api_route("/pay/acompte/{n}", methods=["POST", "GET"])
async def create_acompte_link(n: int, request: Request):
    raw_body = await request.body()
    print("📩 Webhook reçu depuis Monday:", raw_body.decode("utf-8", errors="ignore"))

    try:
        body = await request.json()
    except Exception:
        body = {}

    if "challenge" in body:
        return {"challenge": body["challenge"]}
    if not body:
        return {"status": "ok", "message": "Webhook test accepted"}

    evt = body.get("event") or body.get("payload") or {}
    label = None

    try:
        val = evt.get("value")
        if isinstance(val, str):
            val = _json.loads(val)
        if isinstance(val, dict):
            label = val.get("label") or val.get("label", {}).get("text")
    except Exception:
        pass

    expected_label = f"Générer acompte {n}"
    if label and label != expected_label:
        return {"status": "ignored", "reason": f"label={label} != {expected_label}"}

    item_id = int(evt.get("itemId") or evt.get("pulseId"))
    item_name = evt.get("pulseName") or "Client"

    cols = get_item_columns(item_id, [settings.EMAIL_COLUMN_ID, settings.ADDRESS_COLUMN_ID])
    email = (cols.get(settings.EMAIL_COLUMN_ID, {}) or {}).get("text") or ""
    address = (cols.get(settings.ADDRESS_COLUMN_ID, {}) or {}).get("text") or ""

    formula_id = settings.FORMULA_COLUMN_IDS.get(str(n))
    amount_euros = get_formula_display_value(item_id, formula_id)
    amount_cents = cents_from_str(amount_euros)
    iban_value = get_formula_display_value(item_id, settings.IBAN_FORMULA_COLUMN_ID)
    api_key = _choose_api_key(iban_value)

    url = create_payment(api_key, amount_cents, email, address, item_name,
                         metadata={"customer_id": item_id, "acompte": str(n)})

    link_col = settings.LINK_COLUMN_IDS.get(str(n))
    set_link_in_column(item_id, settings.MONDAY_BOARD_ID, link_col, url, text="Payer")
    return {"status": "ok", "acompte": n, "payment_url": url}


# --- Création de devis Evoliz ---
class QuoteRequest(BaseModel):
    client_name: str
    address: str
    postcode: str
    city: str
    description: str
    amount_ht: float

@app.post("/quote/create")
async def create_quote(payload: QuoteRequest):
    try:
        token = evoliz.get_access_token()
        client_id = evoliz.create_client_if_needed(token, {
            "name": payload.client_name,
            "address": payload.address,
            "postcode": payload.postcode,
            "city": payload.city
        })
        quote = evoliz.create_quote(token, client_id, {
            "description": payload.description,
            "amount_ht": payload.amount_ht
        })
        return {"status": "ok", "quote_id": quote.get("quoteid")}
    except Exception as e:
        raise HTTPException(500, f"Erreur lors de la création du devis : {e}")
