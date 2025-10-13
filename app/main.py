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

app = FastAPI(title="ENERGYZ PayPlug API")

# --- Health ----
@app.get("/")
def root():
    return {"status": "ok", "brand": settings.BRAND_NAME}

@app.get("/health")
def health():
    return {"status": "ok", "service": "energyz-payplug-api"}


# --- Debug ---
@app.get("/debug/check/{item_id}/{n}")
def debug_check(item_id: int, n: int):
    formula_id = settings.FORMULA_COLUMN_IDS.get(str(n))
    link_col = settings.LINK_COLUMN_IDS.get(str(n))

    amount_display = get_formula_display_value(item_id, formula_id) if formula_id else ""
    iban_display = get_formula_display_value(item_id, settings.IBAN_FORMULA_COLUMN_ID) if settings.IBAN_FORMULA_COLUMN_ID else ""

    cols = get_item_columns(item_id, [c for c in [settings.EMAIL_COLUMN_ID, settings.ADDRESS_COLUMN_ID] if c])
    email = (cols.get(settings.EMAIL_COLUMN_ID, {}) or {}).get("text") or ""
    address = (cols.get(settings.ADDRESS_COLUMN_ID, {}) or {}).get("text") or ""

    api_key = _choose_api_key(iban_display)

    return {
        "item_id": item_id,
        "n": n,
        "formula_id_used": formula_id,
        "amount_display": amount_display,
        "iban_display": iban_display,
        "email": email,
        "address": address,
        "link_col_used": link_col,
        "api_key_found": bool(api_key),
    }


# --- Endpoint principal ---
@app.api_route("/pay/acompte/{n}", methods=["POST", "GET"])
async def create_acompte_link(n: int, request: Request):
    """
    Endpoint principal pour générer un lien PayPlug.
    Accepte POST (webhook réel) et GET (test Monday).
    """
    raw_body = await request.body()
    print("📩 Webhook reçu depuis Monday (RAW):", raw_body.decode("utf-8", errors="ignore"))

    try:
        body = await request.json()
    except Exception:
        body = {}

    # ✅ Test de connexion
    if "challenge" in body:
        return {"challenge": body["challenge"]}

    if not body:
        return {"status": "ok", "message": "Webhook test accepted by Monday"}

    # --- Lecture de l'événement ---
    evt = body.get("event") or body.get("payload") or {}
    label = None

    # --- Extraction du label (gère tous les formats Monday) ---
    try:
        val = evt.get("value")
        if isinstance(val, str):
            try:
                val = _json.loads(val)
            except Exception:
                val = {}
        if isinstance(val, dict):
            if isinstance(val.get("label"), dict):
                label = val["label"].get("text")
            else:
                label = val.get("label")
    except Exception:
        pass

    expected_label = f"Générer acompte {n}"
    if label and label != expected_label:
        return {"status": "ignored", "reason": f"label={label} != {expected_label}"}

    # --- Identification de l'item ---
    item_id = evt.get("itemId") or evt.get("pulseId")
    if not item_id:
        raise HTTPException(400, "Missing itemId or pulseId in Monday payload")
    item_id = int(item_id)

    item_name = evt.get("pulseName") or "Client"

    # --- Lecture des infos complémentaires ---
    column_ids = [cid for cid in [settings.EMAIL_COLUMN_ID, settings.ADDRESS_COLUMN_ID] if cid]
    cols = get_item_columns(item_id, column_ids) if column_ids else {}
    email = (cols.get(settings.EMAIL_COLUMN_ID, {}) or {}).get("text") or ""
    address = (cols.get(settings.ADDRESS_COLUMN_ID, {}) or {}).get("text") or ""

    # --- Montant ---
    formula_id = settings.FORMULA_COLUMN_IDS.get(str(n))
    if not formula_id:
        raise HTTPException(400, f"Formula column not configured for acompte {n}")
    amount_euros = get_formula_display_value(item_id, formula_id)
    amount_cents = cents_from_str(amount_euros)
    if amount_cents <= 0:
        raise HTTPException(400, f"Invalid amount for acompte {n}: '{amount_euros}'")

    # --- IBAN & clé API ---
    iban_display_value = get_formula_display_value(item_id, settings.IBAN_FORMULA_COLUMN_ID)
    api_key = _choose_api_key(iban_display_value)
    if not api_key:
        raise HTTPException(400, f"Unknown IBAN key '{iban_display_value}' for PayPlug mapping")

    # --- Création du paiement ---
    url = create_payment(
        api_key=api_key,
        amount_cents=amount_cents,
        email=email,
        address=address,
        customer_name=item_name,
        metadata={"customer_id": item_id, "acompte": str(n)},
    )

    # --- Écriture du lien sur Monday ---
    link_col = settings.LINK_COLUMN_IDS.get(str(n))
    if not link_col:
        raise HTTPException(400, f"Link column not configured for acompte {n}")

    set_link_in_column(item_id, settings.MONDAY_BOARD_ID, link_col, url, text="Payer")

    print(f"✅ Lien PayPlug écrit pour item {item_id} ({expected_label}) → {url}")
    return {"status": "ok", "acompte": n, "payment_url": url}


# --- Endpoint pour créer plusieurs liens ---
@app.post("/pay/all")
async def create_all_links(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    out: dict[str, Any] = {}
    for n in (1, 2, 3, 4):
        if str(n) in settings.LINK_COLUMN_IDS and str(n) in settings.FORMULA_COLUMN_IDS:
            try:
                out[str(n)] = await create_acompte_link(n, request)
            except HTTPException as e:
                out[str(n)] = {"status": "error", "detail": e.detail}
    return out


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


# --- Test direct Render → Monday ---
@app.get("/debug/test_write/{item_id}")
def debug_test_write(item_id: int):
    try:
        link_col = settings.LINK_COLUMN_IDS.get("1")
        if not link_col:
            raise HTTPException(400, "Colonne de lien pour acompte 1 non configurée")

        test_url = "https://example.com/test"
        set_link_in_column(
            item_id=item_id,
            board_id=settings.MONDAY_BOARD_ID,
            column_id=link_col,
            url=test_url,
            text="Lien de test ✅",
        )
        return {
            "status": "ok",
            "message": f"Lien écrit dans {link_col}",
            "url": test_url,
            "item_id": item_id,
        }
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# --- Nouvel endpoint : Création de devis Evoliz ---
from pydantic import BaseModel
from . import evoliz


class QuoteRequest(BaseModel):
    client_name: str
    address: str
    postcode: str
    city: str
    description: str
    amount_ht: float


@app.post("/quote/create", summary="Create Quote From Monday")
async def create_quote_from_monday(payload: QuoteRequest):
    """
    Reçoit un JSON depuis Monday ou Swagger pour créer un devis sur Evoliz.
    """
    try:
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

        return {"status": "ok", "quote_id": quote.get("quoteid")}
    except Exception as e:
        raise HTTPException(500, f"Erreur lors de la création du devis : {e}")
