from fastapi import FastAPI, HTTPException, Body, Request
from typing import Any, Optional
import json as _json
import requests

from .config import settings
from .monday import (
    get_item_columns,
    get_formula_display_value,
    set_link_in_column,
    set_status,
)
from .payments import create_payment, cents_from_str, _choose_api_key
from . import evoliz

app = FastAPI(title="ENERGYZ PayPlug API")

# -----------------------
# Helpers (Monday files)
# -----------------------
def _monday_headers():
    return {"Authorization": settings.MONDAY_API_KEY}

def upload_pdf_to_files_column(item_id: int, files_column_id: str, pdf_url: str, filename: str):
    # 1) Télécharger le PDF Evoliz
    r = requests.get(pdf_url, timeout=30)
    r.raise_for_status()
    pdf_bytes = r.content

    # 2) Upload GraphQL multipart
    api_url = settings.MONDAY_API_URL
    query = """
      mutation ($file: File!, $itemId: ID!, $columnId: String!) {
        add_file_to_column (file: $file, item_id: $itemId, column_id: $columnId) { id }
      }
    """
    variables = {"file": None, "itemId": item_id, "columnId": files_column_id}
    files = {"0": (filename, pdf_bytes, "application/pdf")}
    data = {
        "query": query,
        "variables": _json.dumps(variables),
        "map": _json.dumps({"0": ["variables.file"]}),
    }
    resp = requests.post(api_url, headers=_monday_headers(), files=files, data=data, timeout=60)
    resp.raise_for_status()
    j = resp.json()
    if "errors" in j:
        raise RuntimeError(f"Monday add_file_to_column error: {j['errors']}")
    return j

# -------- Lecture robuste du Montant HT (formula OU numbers) --------
def _read_amount_ht(item_id: int, amount_column_id: Optional[str]) -> tuple[str, float]:
    """
    1) essaie via get_formula_display_value (si c'est une formule),
    2) sinon lit le texte de la colonne (si numbers).
    Retourne (raw_str, parsed_float).
    """
    raw = ""
    if amount_column_id:
        # tentative 1: "formula display"
        try:
            raw = get_formula_display_value(item_id, amount_column_id) or ""
        except Exception:
            raw = ""
        # tentative 2: lecture "text" de la colonne
        if not raw:
            cols = get_item_columns(item_id, [amount_column_id])
            raw = (cols.get(amount_column_id, {}) or {}).get("text") or ""

    try:
        val = float(str(raw).replace("€", "").replace(" ", "").replace(",", ".").strip() or "0")
    except Exception:
        val = 0.0
    return raw, val

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
    iban_display = get_formula_display_value(item_id, settings.IBAN_FORMULA_COLUMN_ID) if getattr(settings, "IBAN_FORMULA_COLUMN_ID", None) else ""

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
# Evoliz: création devis (Swagger / API)
# =======================
from pydantic import BaseModel, field_validator

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

# =======================
# DEBUG: preview des données lues pour un devis
# =======================
@app.get("/debug/quote/preview/{item_id}")
def debug_quote_preview(item_id: int):
    try:
        # Colonnes à lire
        col_ids = []
        for name in [
            "CLIENT_TYPE_COLUMN_ID",
            "VAT_NUMBER_COLUMN_ID",
            "ADDRESS_COLUMN_ID",
            # POSTCODE/CITY/DESCRIPTION sont optionnels
            "POSTCODE_COLUMN_ID",
            "CITY_COLUMN_ID",
            "DESCRIPTION_COLUMN_ID",
        ]:
            cid = getattr(settings, name, None)
            if cid:
                col_ids.append(cid)

        amount_column_id = getattr(settings, "QUOTE_AMOUNT_FORMULA_ID", None)
        if amount_column_id:
            col_ids.append(amount_column_id)

        cols = get_item_columns(item_id, col_ids) if col_ids else {}

        def col_text(cid: Optional[str]) -> str:
            if not cid:
                return ""
            return (cols.get(cid, {}) or {}).get("text") or ""

        client_type_raw = col_text(getattr(settings, "CLIENT_TYPE_COLUMN_ID", None))
        vat_number = col_text(getattr(settings, "VAT_NUMBER_COLUMN_ID", None)) or None
        address = col_text(getattr(settings, "ADDRESS_COLUMN_ID", None))
        postcode = col_text(getattr(settings, "POSTCODE_COLUMN_ID", None))
        city = col_text(getattr(settings, "CITY_COLUMN_ID", None))
        description = col_text(getattr(settings, "DESCRIPTION_COLUMN_ID", None))

        # Montant HT robuste
        amount_ht_str, amount_ht = _read_amount_ht(item_id, amount_column_id)

        # Normalisation type
        t = (client_type_raw or "").strip().lower()
        client_type = "Professionnel" if t in ["professionnel", "pro", "b2b", "entreprise"] else "Particulier"

        ok = True
        reasons = []
        if amount_ht <= 0:
            ok = False
            reasons.append(f"Montant HT lu '{amount_ht_str}' → doit être > 0 (QUOTE_AMOUNT_FORMULA_ID).")
        if client_type == "Professionnel" and not vat_number:
            ok = False
            reasons.append("TVA intracom vide alors que Type client = Professionnel (VAT_NUMBER_COLUMN_ID).")

        return {
            "status": "ok" if ok else "error",
            "can_create_quote": ok,
            "reasons": reasons,
            "read_values": {
                "client_type_raw": client_type_raw,
                "client_type_normalized": client_type,
                "vat_number": vat_number,
                "address_text": address,
                "postcode": postcode,
                "city": city,
                "description": description,
                "amount_ht_str": amount_ht_str,
                "amount_ht_parsed": amount_ht,
                "amount_column_id": amount_column_id,
            },
            "env_used": {
                "CLIENT_TYPE_COLUMN_ID": getattr(settings, "CLIENT_TYPE_COLUMN_ID", ""),
                "VAT_NUMBER_COLUMN_ID": getattr(settings, "VAT_NUMBER_COLUMN_ID", ""),
                "ADDRESS_COLUMN_ID": getattr(settings, "ADDRESS_COLUMN_ID", ""),
                "POSTCODE_COLUMN_ID": getattr(settings, "POSTCODE_COLUMN_ID", ""),
                "CITY_COLUMN_ID": getattr(settings, "CITY_COLUMN_ID", ""),
                "DESCRIPTION_COLUMN_ID": getattr(settings, "DESCRIPTION_COLUMN_ID", ""),
                "QUOTE_AMOUNT_FORMULA_ID": getattr(settings, "QUOTE_AMOUNT_FORMULA_ID", ""),
                "QUOTE_LINK_COLUMN_ID": getattr(settings, "QUOTE_LINK_COLUMN_ID", ""),
                "QUOTE_FILES_COLUMN_ID": getattr(settings, "QUOTE_FILES_COLUMN_ID", ""),
            }
        }
    except Exception as e:
        raise HTTPException(500, f"Preview error: {e}")

# -----------------------
# Création de devis via Swagger / API manuelle
# -----------------------
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
            "quote_number": quote.get("document_number"),
            "webdoc_url": quote.get("webdoc"),
            "links_url": quote.get("links"),
            "pdf_url": quote.get("file"),
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

# =======================
# Evoliz: création devis (depuis Monday - webhook)
# =======================
@app.post("/quote/from_monday", summary="Crée un devis Evoliz depuis un item Monday et dépose le PDF")
async def quote_from_monday(request: Request):
    """
    Webhook Monday déclenché par un statut (ex: 'Générer devis').
    - Lit les colonnes configurées dans settings
    - Crée client + devis dans Evoliz (TVA 20% forcée côté evoliz.py)
    - Dépose le PDF du devis dans la colonne lien (QUOTE_LINK_COLUMN_ID)
    - (Option) Bascule un statut (QUOTE_STATUS_COLUMN_ID => QUOTE_STATUS_AFTER_CREATE)
    - (Option) Upload le PDF dans la colonne Files (QUOTE_FILES_COLUMN_ID)
    """
    raw = await request.body()
    print(f"📩 Webhook Quote RAW: {raw.decode('utf-8', errors='ignore')}")
    try:
        body = await request.json()
    except Exception:
        body = {}

    # Challenge webhook
    if "challenge" in body:
        return {"challenge": body["challenge"]}

    evt = body.get("event") or body.get("payload") or {}
    item_id = evt.get("itemId") or evt.get("pulseId")
    if not item_id:
        raise HTTPException(400, "itemId/pulseId manquant")
    item_id = int(item_id)

    # Filtre label déclencheur
    trigger_label = getattr(settings, "QUOTE_TRIGGER_LABEL", "Générer devis")
    label = None
    try:
        val = evt.get("value")
        if isinstance(val, str):
            try:
                val = _json.loads(val)
            except Exception:
                val = {}
        if isinstance(val, dict):
            label = (val.get("label") or {}).get("text") if isinstance(val.get("label"), dict) else val.get("label")
    except Exception:
        pass
    if label and label != trigger_label:
        print(f"⚠️ Quote ignoré: label={label} (attendu: {trigger_label})")
        return {"status": "ignored", "reason": f"label={label} != {trigger_label}"}

    # ----- Colonnes à lire -----
    col_ids = []
    for name in [
        "CLIENT_TYPE_COLUMN_ID",
        "VAT_NUMBER_COLUMN_ID",
        "ADDRESS_COLUMN_ID",
        # optionnels
        "POSTCODE_COLUMN_ID",
        "CITY_COLUMN_ID",
        "DESCRIPTION_COLUMN_ID",
    ]:
        cid = getattr(settings, name, None)
        if cid:
            col_ids.append(cid)

    amount_column_id = getattr(settings, "QUOTE_AMOUNT_FORMULA_ID", None)
    if amount_column_id:
        col_ids.append(amount_column_id)

    cols = get_item_columns(item_id, col_ids) if col_ids else {}

    def col_text(cid: Optional[str]) -> str:
        if not cid:
            return ""
        return (cols.get(cid, {}) or {}).get("text") or ""

    client_type = col_text(getattr(settings, "CLIENT_TYPE_COLUMN_ID", None)) or "Particulier"
    vat_number = col_text(getattr(settings, "VAT_NUMBER_COLUMN_ID", None)) or None
    address = col_text(getattr(settings, "ADDRESS_COLUMN_ID", None))
    postcode = col_text(getattr(settings, "POSTCODE_COLUMN_ID", None))
    city = col_text(getattr(settings, "CITY_COLUMN_ID", None))
    description = col_text(getattr(settings, "DESCRIPTION_COLUMN_ID", None))
    client_name = evt.get("pulseName") or "Client"

    # Montant HT robuste
    amount_ht_str, amount_ht = _read_amount_ht(item_id, amount_column_id)
    if amount_ht <= 0:
        raise HTTPException(400, f"Montant HT invalide (QUOTE_AMOUNT_FORMULA_ID): '{amount_ht_str}'")

    # Normalisation type client
    t = client_type.strip().lower()
    client_type = "Professionnel" if t in ["professionnel", "pro", "b2b", "entreprise"] else "Particulier"
    if client_type == "Professionnel" and not vat_number:
        raise HTTPException(400, "Client Professionnel : la colonne TVA intracom est vide.")

    # ----- Evoliz -----
    token = evoliz.get_access_token()
    client_info = {
        "name": client_name,
        "address": address,
        "postcode": postcode,
        "city": city,
        "client_type": client_type,
        "vat_number": vat_number,
    }
    quote_info = {"description": description or f"Devis item {item_id}", "amount_ht": amount_ht}
    quote = evoliz.create_quote(token, evoliz.create_client_if_needed(token, client_info), quote_info)
    print(f"✅ Devis Evoliz créé: {quote}")

    pdf_url = quote.get("file")
    doc_number = quote.get("document_number") or quote.get("quotenumber") or "Devis"

    # Lien PDF dans la colonne Lien
    link_col = getattr(settings, "QUOTE_LINK_COLUMN_ID", None)
    if link_col and pdf_url:
        set_link_in_column(item_id, settings.MONDAY_BOARD_ID, link_col, pdf_url, text=f"Devis {doc_number}")
        print(f"🧾 PDF déposé (Lien): {pdf_url}")

    # Upload PDF dans la colonne Fichiers (si configurée)
    files_col = getattr(settings, "QUOTE_FILES_COLUMN_ID", None)
    if files_col and pdf_url:
        try:
            upload_pdf_to_files_column(item_id, files_col, pdf_url, filename=f"Devis_{doc_number}.pdf")
            print("📎 PDF uploadé dans la colonne Fichiers.")
        except Exception as e:
            print(f"⚠️ Upload fichier Monday échoué: {e}")

    # (Option) statut après création
    status_col = getattr(settings, "QUOTE_STATUS_COLUMN_ID", None)
    status_label = getattr(settings, "QUOTE_STATUS_AFTER_CREATE", None)
    if status_col and status_label:
        set_status(item_id, settings.MONDAY_BOARD_ID, status_col, status_label)

    return {
        "status": "ok",
        "item_id": item_id,
        "quote_id": quote.get("quoteid"),
        "quote_number": doc_number,
        "pdf_url": pdf_url,
        "webdoc_url": quote.get("webdoc"),
        "links_url": quote.get("links"),
        "client_type": client_type,
    }
