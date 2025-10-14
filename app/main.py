from fastapi import FastAPI, HTTPException, Body, Request
from typing import Any, Optional
import json as _json
import requests
import re

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

# =========================
# Helpers Monday / Utilitaires
# =========================
def _monday_headers():
    return {"Authorization": settings.MONDAY_API_KEY}

def _graphql(query: str, variables: dict) -> dict:
    resp = requests.post(
        settings.MONDAY_API_URL,
        headers={
            "Authorization": settings.MONDAY_API_KEY,
            "Content-Type": "application/json",
        },
        json={"query": query, "variables": variables},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data

def set_number_column_value(item_id: int, column_id: str, value: float):
    """Écrit une valeur dans une colonne Numbers."""
    query = """
      mutation ($board_id: ID!, $item_id: ID!, $column_id: String!, $val: JSON!) {
        change_simple_column_value(
          board_id: $board_id,
          item_id: $item_id,
          column_id: $column_id,
          value: $val
        ){ id }
      }
    """
    _graphql(query, {
        "board_id": settings.MONDAY_BOARD_ID,
        "item_id": item_id,
        "column_id": column_id,
        "val": value,
    })

def upload_pdf_to_files_column(item_id: int, files_column_id: str, pdf_api_url: str, filename: str, token: str):
    """Télécharge le PDF Evoliz (avec Bearer token) puis l'upload dans la colonne Files."""
    r = requests.get(pdf_api_url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    pdf_bytes = r.content

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
    resp = requests.post(settings.MONDAY_API_URL, headers=_monday_headers(), files=files, data=data, timeout=60)
    resp.raise_for_status()
    j = resp.json()
    if "errors" in j:
        raise RuntimeError(f"Monday add_file_to_column error: {j['errors']}")
    return j

def _read_amount_ht(item_id: int, amount_column_id: Optional[str]) -> tuple[str, float]:
    raw = ""
    if amount_column_id:
        try:
            raw = get_formula_display_value(item_id, amount_column_id) or ""
        except Exception:
            raw = ""
        if not raw:
            cols = get_item_columns(item_id, [amount_column_id])
            raw = (cols.get(amount_column_id, {}) or {}).get("text") or ""
    try:
        val = float(str(raw).replace("€", "").replace(" ", "").replace(",", ".").strip() or "0")
    except Exception:
        val = 0.0
    return raw, val

def _read_vat_rate(item_id: int) -> float:
    """Lit la TVA depuis la colonne Numbers si configurée, sinon DEFAULT_VAT_RATE."""
    col_id = settings.VAT_RATE_COLUMN_ID
    if not col_id:
        return settings.DEFAULT_VAT_RATE
    cols = get_item_columns(item_id, [col_id])
    raw = (cols.get(col_id, {}) or {}).get("text") or ""
    try:
        raw_clean = str(raw).replace("%", "").replace(",", ".").strip()
        return float(raw_clean) if raw_clean else settings.DEFAULT_VAT_RATE
    except Exception:
        return settings.DEFAULT_VAT_RATE

def _guess_postcode_city(address_text: str) -> tuple[str, str]:
    if address_text:
        m = re.search(r"(\b\d{5}\b)\s+([A-Za-zÀ-ÿ'’\-\s]+)$", address_text.strip())
        if m:
            return m.group(1), m.group(2).strip()
    return "00000", "N/A"

# =========================
# Health / Debug
# =========================
@app.get("/")
def root():
    return {"status": "ok", "brand": settings.BRAND_NAME}

@app.get("/health")
def health():
    return {"status": "ok", "service": "energyz-payplug-api"}

# --- Test login Evoliz ---
@app.get("/debug/evoliz/login")
def debug_evoliz_login():
    """Ping Evoliz: renvoie un token si les clés et l'URL de base sont correctes."""
    try:
        token = evoliz.get_access_token()
        return {"status": "ok", "token_preview": token[:10] + "..."}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

# =========================
# PayPlug (inchangé)
# =========================
@app.api_route("/pay/acompte/{n}", methods=["POST", "GET"])
async def create_acompte_link(n: int, request: Request):
    raw_body = await request.body()
    print(f"📩 Webhook reçu depuis Monday (RAW): {raw_body.decode('utf-8', errors='ignore')}")
    try:
        body = await request.json()
    except Exception:
        body = {}

    if "challenge" in body:
        return {"challenge": body["challenge"]}
    if not body:
        return {"status": "ok", "message": "Webhook test accepté"}

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
            label = (val.get("label") or {}).get("text") if isinstance(val.get("label"), dict) else val.get("label")
    except Exception:
        pass

    expected_label = f"Générer acompte {n}"
    if label and label != expected_label:
        return {"status": "ignored", "reason": f"label={label} != {expected_label}"}

    item_id = evt.get("itemId") or evt.get("pulseId")
    if not item_id:
        raise HTTPException(400, "itemId/pulseId manquant")
    item_id = int(item_id)
    item_name = evt.get("pulseName") or "Client"

    column_ids = [cid for cid in [settings.EMAIL_COLUMN_ID, settings.ADDRESS_COLUMN_ID] if cid]
    cols = get_item_columns(item_id, column_ids) if column_ids else {}
    email = (cols.get(settings.EMAIL_COLUMN_ID, {}) or {}).get("text") or ""
    address = (cols.get(settings.ADDRESS_COLUMN_ID, {}) or {}).get("text") or ""

    formula_id = settings.FORMULA_COLUMN_IDS.get(str(n))
    if not formula_id:
        raise HTTPException(400, f"Aucune colonne formule configurée pour acompte {n}")
    amount_euros = get_formula_display_value(item_id, formula_id)
    amount_cents = cents_from_str(amount_euros)
    if amount_cents <= 0:
        raise HTTPException(400, f"Montant invalide pour acompte {n}: '{amount_euros}'")

    iban_display_value = get_formula_display_value(item_id, settings.IBAN_FORMULA_COLUMN_ID)
    api_key = _choose_api_key(iban_display_value)
    if not api_key:
        raise HTTPException(400, f"IBAN non reconnu : '{iban_display_value}'")

    url = create_payment(
        api_key=api_key,
        amount_cents=amount_cents,
        email=email,
        address=address,
        customer_name=item_name,
        metadata={"customer_id": item_id, "acompte": str(n)},
    )

    link_col = settings.LINK_COLUMN_IDS.get(str(n))
    if not link_col:
        raise HTTPException(400, f"Aucune colonne lien configurée pour acompte {n}")
    set_link_in_column(item_id, settings.MONDAY_BOARD_ID, link_col, url, text="Payer")
    return {"status": "ok", "acompte": n, "payment_url": url}

# =========================
# Devis — Preview debug
# =========================
@app.get("/debug/quote/preview/{item_id}")
def debug_quote_preview(item_id: int):
    try:
        col_ids = []
        for name in [
            "CLIENT_TYPE_COLUMN_ID",
            "VAT_NUMBER_COLUMN_ID",
            "ADDRESS_COLUMN_ID",
            "POSTCODE_COLUMN_ID",
            "CITY_COLUMN_ID",
            "DESCRIPTION_COLUMN_ID",
        ]:
            cid = getattr(settings, name, None)
            if cid:
                col_ids.append(cid)
        amount_column_id = settings.QUOTE_AMOUNT_FORMULA_ID
        if amount_column_id:
            col_ids.append(amount_column_id)
        if settings.VAT_RATE_COLUMN_ID:
            col_ids.append(settings.VAT_RATE_COLUMN_ID)

        cols = get_item_columns(item_id, col_ids) if col_ids else {}

        def col_text(cid: Optional[str]) -> str:
            if not cid:
                return ""
            return (cols.get(cid, {}) or {}).get("text") or ""

        client_type_raw = col_text(settings.CLIENT_TYPE_COLUMN_ID)
        vat_number = col_text(settings.VAT_NUMBER_COLUMN_ID) or None
        address = col_text(settings.ADDRESS_COLUMN_ID)
        postcode = col_text(settings.POSTCODE_COLUMN_ID)
        city = col_text(settings.CITY_COLUMN_ID)
        description = col_text(settings.DESCRIPTION_COLUMN_ID)

        amount_ht_str, amount_ht = _read_amount_ht(item_id, amount_column_id)
        vat_rate = _read_vat_rate(item_id)

        t = (client_type_raw or "").strip().lower()
        client_type = "Professionnel" if t in ["professionnel", "pro", "b2b", "entreprise"] else "Particulier"

        ok = True
        reasons = []
        if amount_ht <= 0:
            ok = False
            reasons.append(f"Montant HT lu '{amount_ht_str}' → doit être > 0 (QUOTE_AMOUNT_FORMULA_ID).")

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
                "vat_rate": vat_rate,
            }
        }
    except Exception as e:
        raise HTTPException(500, f"Preview error: {e}")

# =========================
# Devis — Swagger manuel
# =========================
from pydantic import BaseModel, field_validator
class QuoteRequest(BaseModel):
    client_name: str
    address: str
    postcode: str
    city: str
    description: str
    amount_ht: float
    client_type: str = "Particulier"
    vat_number: Optional[str] = None
    vat_rate: Optional[float] = None

    @field_validator("client_type")
    @classmethod
    def _normalize_type(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v in ["particulier", "b2c", "perso", "privé", "prive"]:
            return "Particulier"
        if v in ["professionnel", "pro", "b2b", "
