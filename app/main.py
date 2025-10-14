from fastapi import FastAPI, HTTPException, Body, Request
from fastapi.responses import JSONResponse
from typing import Any, Optional
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

# -----------------------
# Health checks
# -----------------------
@app.get("/")
def root():
    return {"status": "ok", "brand": settings.BRAND_NAME}

@app.get("/health")
def health():
    return {"status": "ok", "service": "energyz-payplug-api"}

# -----------------------
# Debug Monday: lecture rapide
# -----------------------
@app.get("/debug/check/{item_id}/{n}")
def debug_check(item_id: int, n: int):
    print(f"🔍 Debug check lancé pour item {item_id}, acompte {n}")

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

# -----------------------
# Génération lien PayPlug
# -----------------------
@app.api_route("/pay/acompte/{n}", methods=["POST", "GET"])
async def create_acompte_link(n: int, request: Request):
    """
    Crée un lien PayPlug pour l'acompte spécifié.
    Géré via webhook Monday (POST) ou test manuel (GET).
    """
    raw_body = await request.body()
    print(f"📩 Webhook reçu depuis Monday (RAW): {raw_body.decode('utf-8', errors='ignore')}")

    try:
        body = await request.json()
    except Exception:
        body = {}

    # Challenge webhook
    if "challenge" in body:
        return {"challenge": body["challenge"]}

    if not body:
        return {"status": "ok", "message": "Webhook test accepté"}

    # Lecture événement Monday
    evt = body.get("event") or body.get("payload") or {}
    label = None

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
        print(f"⚠️ Label ignoré : {label} (attendu : {expected_label})")
        return {"status": "ignored", "reason": f"label={label} != {expected_label}"}

    # Item
    item_id = evt.get("itemId") or evt.get("pulseId")
    if not item_id:
        raise HTTPException(400, "itemId ou pulseId manquant dans le payload Monday")
    item_id = int(item_id)
    item_name = evt.get("pulseName") or "Client"

    # Infos client
    column_ids = [cid for cid in [settings.EMAIL_COLUMN_ID, settings.ADDRESS_COLUMN_ID] if cid]
    cols = get_item_columns(item_id, column_ids) if column_ids else {}
    email = (cols.get(settings.EMAIL_COLUMN_ID, {}) or {}).get("text") or ""
    address = (cols.get(settings.ADDRESS_COLUMN_ID, {}) or {}).get("text") or ""

    # Montant
    formula_id = settings.FORMULA_COLUMN_IDS.get(str(n))
    if not formula_id:
        raise HTTPException(400, f"Aucune colonne formule configurée pour acompte {n}")

    amount_euros = get_formula_display_value(item_id, formula_id)
    amount_cents = cents_from_str(amount_euros)
    if amount_cents <= 0:
        raise HTTPException(400, f"Montant invalide pour acompte {n}: '{amount_euros}'")

    # Choix clé PayPlug selon IBAN
    iban_display_value = get_formula_display_value(item_id, settings.IBAN_FORMULA_COLUMN_ID)
    api_key = _choose_api_key(iban_display_value)
    if not api_key:
        raise HTTPException(400, f"IBAN non reconnu : '{iban_display_value}'")

    # Création paiement PayPlug
    url = create_payment(
        api_key=api_key,
        amount_cents=amount_cents,
        email=email,
        address=address,
        customer_name=item_name,
        metadata={"customer_id": item_id, "acompte": str(n)},
    )

    # Écriture lien dans Monday
    link_col = settings.LINK_COLUMN_IDS.get(str(n))
    if not link_col:
        raise HTTPException(400, f"Aucune colonne lien configurée pour acompte {n}")

    set_link_in_column(item_id, settings.MONDAY_BOARD_ID, link_col, url, text="Payer")
    print(f"✅ Lien PayPlug écrit sur Monday : {url}")

    return {"status": "ok", "acompte": n, "payment_url": url}

# -----------------------
# Générer plusieurs liens
# -----------------------
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

# -----------------------
# Notification PayPlug
# -----------------------
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

# -----------------------
# Test écriture Monday
# -----------------------
@app.get("/debug/test_write/{item_id}")
def debug_test_write(item_id: int):
    try:
        link_col = settings.LINK_COLUMN_IDS.get("1")
        if not link_col:
            raise HTTPException(400, "Colonne lien acompte 1 non configurée")

        test_url = "https://example.com/test"
        set_link_in_column(
            item_id=item_id,
            board_id=settings.MONDAY_BOARD_ID,
            column_id=link_col,
            url=test_url,
            text="Lien de test ✅",
        )
        return {"status": "ok", "url": test_url, "item_id": item_id}
    except Exception as e:
        raise HTTPException(500, detail=str(e))

# =======================
# Evoliz: création devis
# =======================
from pydantic import BaseModel, field_validator
from . import evoliz

class QuoteRequest(BaseModel):
    client_name: str
    address: str
    postcode: str
    city: str
    description: str
    amount_ht: float
    client_type: str = "Particulier"     # "Particulier" ou "Professionnel"
    vat_number: Optional[str] = None     # requis si Professionnel

    @field_validator("client_type")
    @classmethod
    def _normalize_type(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v in ["particulier", "b2c", "perso", "privé", "prive"]:
            return "Particulier"
        if v in ["professionnel", "pro", "b2b", "entreprise"]:
            return "Professionnel"
        return "Particulier"

@app.post("/quote/create", summary="Create Quote From Monday")
async def create_quote_from_monday(payload: QuoteRequest):
    """
    Crée un devis Evoliz à partir d'une requête JSON (via Monday ou Swagger).
    - Si client_type = Professionnel => vat_number obligatoire
    - TVA forcée à 20% côté evoliz.create_quote()
    """
    try:
        print(f"🧾 Création de devis Evoliz pour client : {payload.client_name} ({payload.client_type})")

        if payload.client_type == "Professionnel" and not payload.vat_number:
            raise HTTPException(400, "Client Professionnel : 'vat_number' (TVA intracom) est requis.")

        client_info = {
            "name": payload.client_name,
            "address": payload.address,
            "postcode": payload.postcode,
            "city": payload.city,
            "client_type": payload.client_type,
            "vat_number": payload.vat_number,
        }
        quote_info = {
            "description": payload.description,
            "amount_ht": payload.amount_ht,
        }

        token = evoliz.get_access_token()
        client_id = evoliz.create_client_if_needed(token, client_info)
        quote = evoliz.create_quote(token, client_id, quote_info)

        print(f"✅ Devis créé avec succès : {quote}")
        return {
            "status": "ok",
            "quote_id": quote.get("quoteid"),
            "quote_number": quote.get("document_number"),  # numéro lisible
            "webdoc_url": quote.get("webdoc"),             # page web devis
            "links_url": quote.get("links"),               # fiche Evoliz
            "pdf_url": quote.get("file"),                  # PDF direct
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Erreur Evoliz : {e}")
        raise HTTPException(500, f"Erreur lors de la création du devis : {e}")

# -----------------------
# Debug Evoliz login
# -----------------------
@app.get("/debug/evoliz/login")
def debug_evoliz_login():
    """Teste la connexion à l'API Evoliz (renvoie un token si OK)"""
    try:
        token = evoliz.get_access_token()
        return {"status": "ok", "token_preview": token[:10] + "..."}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
