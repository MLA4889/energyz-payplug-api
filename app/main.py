from fastapi import FastAPI, HTTPException, Body, Request
from fastapi.responses import JSONResponse
from typing import Any
import json as _json
from datetime import date

from .config import settings
from .monday import (
    get_item_columns,
    get_formula_display_value,
    set_link_in_column,
    set_status,
)
from .payments import create_payment, cents_from_str, _choose_api_key
from . import evoliz

app = FastAPI(title="ENERGYZ PayPlug + Evoliz API")


# --- Health checks ---
@app.get("/")
def root():
    return {"status": "ok", "brand": settings.BRAND_NAME}

@app.get("/health")
def health():
    return {"status": "ok", "service": "energyz-payplug-api"}


# --- Génération lien PayPlug pour acompte ---
@app.api_route("/pay/acompte/{n}", methods=["POST", "GET"])
async def create_acompte_link(n: int, request: Request):
    """
    Crée un lien PayPlug pour l'acompte spécifié (via webhook Monday ou test manuel)
    """
    try:
        raw = await request.body()
        print(f"📩 Webhook reçu depuis Monday (RAW): {raw.decode('utf-8', errors='ignore')}")
    except:
        raw = b""

    try:
        body = await request.json()
    except Exception:
        body = {}

    if "challenge" in body:
        return {"challenge": body["challenge"]}

    evt = body.get("event") or body.get("payload") or {}
    label = None
    try:
        val = evt.get("value")
        if isinstance(val, str):
            val = _json.loads(val)
        if isinstance(val, dict):
            label = val.get("label", {}).get("text") if isinstance(val.get("label"), dict) else val.get("label")
    except Exception:
        pass

    expected_label = f"Générer acompte {n}"
    if label and label != expected_label:
        print(f"⚠️ Label ignoré : {label} (attendu : {expected_label})")
        return {"status": "ignored"}

    item_id = evt.get("itemId") or evt.get("pulseId")
    if not item_id:
        raise HTTPException(400, "itemId manquant")
    item_id = int(item_id)

    cols = get_item_columns(item_id, [settings.EMAIL_COLUMN_ID, settings.ADDRESS_COLUMN_ID])
    email = (cols.get(settings.EMAIL_COLUMN_ID) or {}).get("text", "")
    address = (cols.get(settings.ADDRESS_COLUMN_ID) or {}).get("text", "")

    formula_id = settings.FORMULA_COLUMN_IDS.get(str(n))
    amount_euros = get_formula_display_value(item_id, formula_id)
    amount_cents = cents_from_str(amount_euros)

    iban_display = get_formula_display_value(item_id, settings.IBAN_FORMULA_COLUMN_ID)
    api_key = _choose_api_key(iban_display)

    url = create_payment(
        api_key=api_key,
        amount_cents=amount_cents,
        email=email,
        address=address,
        customer_name=evt.get("pulseName") or "Client",
        metadata={"customer_id": item_id, "acompte": str(n)},
    )

    link_col = settings.LINK_COLUMN_IDS.get(str(n))
    set_link_in_column(item_id, settings.MONDAY_BOARD_ID, link_col, url, text="Payer acompte")
    print(f"✅ Lien PayPlug écrit dans Monday : {url}")

    return {"status": "ok", "acompte": n, "payment_url": url}


# --- Notification PayPlug ---
@app.post("/pay/notify")
async def payplug_notify(body: dict = Body(...)):
    if body.get("is_paid"):
        meta = body.get("metadata", {}) or {}
        try:
            item_id = int(meta.get("customer_id"))
        except Exception:
            return {"status": "ignored"}
        acompte = str(meta.get("acompte") or "")
        label = settings.STATUS_AFTER_PAY.get(acompte)
        if label:
            set_status(item_id, settings.MONDAY_BOARD_ID, settings.STATUS_COLUMN_ID, label)
    return {"status": "processed"}


# --- Création de devis Evoliz ---
from pydantic import BaseModel

class QuoteRequest(BaseModel):
    client_name: str
    address: str
    postcode: str
    city: str
    description: str
    amount_ht: float

@app.post("/quote/create", summary="Créer un devis Evoliz depuis Monday")
async def create_quote_from_monday(payload: QuoteRequest):
    try:
        print(f"🧾 Création de devis Evoliz pour client : {payload.client_name}")

        client_info = {
            "name": payload.client_name,
            "address": payload.address,
            "postcode": payload.postcode,
            "city": payload.city,
        }
        quote_info = {
            "description": payload.description,
            "amount_ht": payload.amount_ht,
        }

        token = evoliz.get_access_token()
        client_id = evoliz.create_client_if_needed(token, client_info)
        quote = evoliz.create_quote(token, client_id, quote_info)

        print(f"✅ Devis Evoliz créé avec succès : {quote}")
        return {"status": "ok", "quote_id": quote.get("quoteid")}
    except Exception as e:
        print(f"❌ Erreur Evoliz : {e}")
        raise HTTPException(500, f"Erreur lors de la création du devis : {e}")


# --- Test Evoliz connexion ---
@app.get("/debug/evoliz/login")
def debug_evoliz_login():
    try:
        token = evoliz.get_access_token()
        return {"status": "ok", "token_preview": token[:10] + "..."}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
