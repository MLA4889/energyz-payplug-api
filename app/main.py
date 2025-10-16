from fastapi import FastAPI, HTTPException, Body, Request
from fastapi.responses import JSONResponse
from typing import Any
import json as _json

from .config import settings
from .monday import (
    get_item_columns,
    get_formula_display_value,
    set_link_in_column,
    set_status,
)
from .payments import create_payment, cents_from_str, _choose_api_key
from . import evoliz
from pydantic import BaseModel

app = FastAPI(title="ENERGYZ PayPlug API")


# ---------------------------
# ✅ Health check endpoints
# ---------------------------
@app.get("/")
def root():
    return {"status": "ok", "brand": settings.BRAND_NAME}


@app.get("/health")
def health():
    return {"status": "ok", "service": "energyz-payplug-api"}


# ---------------------------
# 🔍 Debug Monday
# ---------------------------
@app.get("/debug/check/{item_id}/{n}")
def debug_check(item_id: int, n: int):
    formula_id = settings.FORMULA_COLUMN_IDS.get(str(n))
    link_col = settings.LINK_COLUMN_IDS.get(str(n))
    amount_display = get_formula_display_value(item_id, formula_id) if formula_id else ""
    iban_display = get_formula_display_value(item_id, settings.IBAN_FORMULA_COLUMN_ID)
    cols = get_item_columns(item_id, [settings.EMAIL_COLUMN_ID, settings.ADDRESS_COLUMN_ID])
    email = cols.get(settings.EMAIL_COLUMN_ID, {}).get("text", "")
    address = cols.get(settings.ADDRESS_COLUMN_ID, {}).get("text", "")
    api_key = _choose_api_key(iban_display)
    return {
        "item_id": item_id,
        "acompte": n,
        "amount": amount_display,
        "iban": iban_display,
        "email": email,
        "address": address,
        "api_key_found": bool(api_key),
        "link_col": link_col,
    }


# ---------------------------
# 💳 Créer un lien PayPlug
# ---------------------------
@app.api_route("/pay/acompte/{n}", methods=["POST", "GET"])
async def create_acompte_link(n: int, request: Request):
    raw_body = await request.body()
    print(f"📩 Webhook Monday reçu : {raw_body.decode('utf-8', errors='ignore')}")

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
            label = val.get("label", {}).get("text") or val.get("label")
    except Exception:
        pass

    expected_label = f"Générer acompte {n}"
    if label and label != expected_label:
        return {"status": "ignored", "reason": f"label={label} != {expected_label}"}

    item_id = evt.get("itemId") or evt.get("pulseId")
    if not item_id:
        raise HTTPException(400, "itemId manquant dans le payload Monday")

    item_id = int(item_id)
    item_name = evt.get("pulseName", "Client")

    # Récup infos client
    cols = get_item_columns(item_id, [settings.EMAIL_COLUMN_ID, settings.ADDRESS_COLUMN_ID])
    email = cols.get(settings.EMAIL_COLUMN_ID, {}).get("text", "")
    address = cols.get(settings.ADDRESS_COLUMN_ID, {}).get("text", "")

    # Montant acompte
    formula_id = settings.FORMULA_COLUMN_IDS.get(str(n))
    if not formula_id:
        raise HTTPException(400, f"Aucune colonne formule pour acompte {n}")

    amount_euros = get_formula_display_value(item_id, formula_id)
    amount_cents = cents_from_str(amount_euros)
    if amount_cents <= 0:
        raise HTTPException(400, f"Montant invalide '{amount_euros}'")

    # Choix clé API PayPlug
    iban_display = get_formula_display_value(item_id, settings.IBAN_FORMULA_COLUMN_ID)
    api_key = _choose_api_key(iban_display)
    if not api_key:
        raise HTTPException(400, f"IBAN non reconnu : {iban_display}")

    # Création paiement
    url = create_payment(
        api_key=api_key,
        amount_cents=amount_cents,
        email=email,
        address=address,
        customer_name=item_name,
        metadata={"customer_id": item_id, "acompte": str(n)},
    )

    # Écrire lien dans Monday
    link_col = settings.LINK_COLUMN_IDS.get(str(n))
    set_link_in_column(item_id, settings.MONDAY_BOARD_ID, link_col, url, "Payer acompte 💳")

    print(f"✅ Lien PayPlug généré : {url}")
    return {"status": "ok", "acompte": n, "payment_url": url}


# ---------------------------
# 🧾 Créer un devis Evoliz
# ---------------------------
class QuoteRequest(BaseModel):
    client_name: str
    address: str
    postcode: str
    city: str
    description: str
    amount_ht: float


@app.post("/quote/create")
async def create_quote_from_monday(payload: QuoteRequest):
    try:
        print(f"🧾 Création devis Evoliz pour {payload.client_name}")

        token = evoliz.get_access_token()
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
        client_id = evoliz.create_client_if_needed(token, client_info)
        quote = evoliz.create_quote(token, client_id, quote_info)
        print(f"✅ Devis créé : {quote}")
        return {"status": "ok", "quote_id": quote.get("quoteid")}
    except Exception as e:
        print(f"❌ Erreur Evoliz : {e}")
        raise HTTPException(500, f"Erreur Evoliz : {e}")


# ---------------------------
# 🧠 Debug Evoliz connexion
# ---------------------------
@app.get("/debug/evoliz/login")
def debug_evoliz_login():
    try:
        token = evoliz.get_access_token()
        return {"status": "ok", "token": token[:10] + "..."}
    except Exception as e:
        raise HTTPException(500, str(e))
