from __future__ import annotations
from typing import Any, Dict, Optional
from fastapi import FastAPI, Body, HTTPException, Request
from .config import settings
from .monday import get_item_columns, get_formula_display_value, set_link_in_column, set_status, extract_address_fields, cv_text
from .payments import create_payment, cents_from_str
from .evoliz import get_access_token, create_client_if_needed, create_quote

app = FastAPI(title=f"{settings.BRAND_NAME} – Monday / Evoliz / PayPlug (V1)")

def _read_vat_rate(cols: Dict[str, Any]) -> float:
    txt = cv_text(cols, settings.VAT_RATE_COLUMN_ID)
    if not txt:
        return settings.DEFAULT_VAT_RATE
    try:
        return float(txt.replace(",", "."))
    except Exception:
        return settings.DEFAULT_VAT_RATE

def _iban_from_item(cols: Dict[str, Any]) -> str:
    # 1) tenter formula
    iban = (settings.IBAN_FORMULA_COLUMN_ID and get_formula_display_value(cols, settings.IBAN_FORMULA_COLUMN_ID)) or ""
    iban = iban.strip()
    if iban:
        return iban
    # 2) fallback par statut "Business Line / Société"
    status = cv_text(cols, settings.BUSINESS_STATUS_COLUMN_ID)
    return settings.PAYPLUG_IBAN_BY_STATUS.get(status, "")

@app.get("/")
def root():
    return {"status": "ok", "brand": settings.BRAND_NAME}

@app.get("/health")
def health():
    return {
        "status": "ok",
        "board": settings.MONDAY_BOARD_ID,
        "payplug_mode": settings.PAYPLUG_MODE,
        "evoliz_company": settings.EVOLIZ_COMPANY_ID,
    }

@app.get("/debug/quote/preview/{item_id}")
def debug_quote_preview(item_id: int):
    info = get_item_columns(item_id)
    cols = info["columns"]
    amount_ht_txt = cv_text(cols, settings.QUOTE_AMOUNT_FORMULA_ID) or "0"
    vat_rate_txt = cv_text(cols, settings.VAT_RATE_COLUMN_ID) or str(settings.DEFAULT_VAT_RATE)
    desc = (settings.DESCRIPTION_COLUMN_ID and get_formula_display_value(cols, settings.DESCRIPTION_COLUMN_ID)) or info["name"]
    vat_number = cv_text(cols, settings.VAT_NUMBER_COLUMN_ID)
    return {
        "item_id": item_id,
        "name": info["name"],
        "description": desc,
        "amount_ht_text": amount_ht_txt,
        "vat_rate_text": vat_rate_txt,
        "vat_number": vat_number,
        "address": extract_address_fields(cols),
    }

@app.get("/debug/payplug/{item_id}")
def debug_payplug(item_id: int):
    info = get_item_columns(item_id)
    cols = info["columns"]
    iban_raw = _iban_from_item(cols)
    mode = settings.PAYPLUG_MODE
    keys = list((settings.PAYPLUG_KEYS_LIVE if mode == "live" else settings.PAYPLUG_KEYS_TEST).keys())
    return {"item_id": item_id, "iban_raw": iban_raw, "mode": mode, "keys_available": keys}

# -------- PayPlug (acompte) --------
@app.api_route("/pay/acompte/{n}", methods=["GET", "POST"])
async def pay_acompte(n: int, item_id: Optional[int] = None, request: Request | None = None):
    # support webhook monday (POST) et test manuel (GET)
    if request and request.method == "POST":
        try:
            payload = await request.json()
            item_id = item_id or int(payload["event"]["pulseId"])
        except Exception:
            pass
    if not item_id:
        raise HTTPException(400, "item_id manquant")

    info = get_item_columns(item_id)
    cols = info["columns"]

    formula_col_id = settings.FORMULA_COLUMN_IDS.get(str(n))
    if not formula_col_id:
        raise HTTPException(400, f"FORMULA_COLUMN_IDS n°{n} non configurée")
    amount_txt = (get_formula_display_value(cols, formula_col_id) or "").strip()
    # si formula vide → zéro
    amount_cents = cents_from_str(amount_txt)
    if amount_cents <= 0:
        raise HTTPException(400, f"Montant d'acompte {n} invalide pour l'item {item_id} (valeur lue='{amount_txt or '0'}').")

    desc = (settings.DESCRIPTION_COLUMN_ID and get_formula_display_value(cols, settings.DESCRIPTION_COLUMN_ID)) or info["name"]
    iban_txt = _iban_from_item(cols)

    pay = create_payment(amount_cents, f"Acompte {n} – {desc}", f"{settings.PUBLIC_BASE_URL}/", iban_txt)

    link_col = settings.LINK_COLUMN_IDS.get(str(n))
    if link_col:
        set_link_in_column(item_id, link_col, pay["url"], f"Payer acompte {n}")

    # statut après paiement (si tu veux l'appliquer ici, sinon laisse au webhook PayPlug)
    return {"status": "ok", "payment": pay}

# -------- Devis depuis Monday --------
@app.post("/quote/from_monday")
async def quote_from_monday_webhook(payload: dict = Body(...)):
    try:
        item_id = int(payload["event"]["pulseId"])
    except Exception:
        raise HTTPException(400, "payload sans item_id")

    label = payload.get("event", {}).get("value")
    if label != settings.QUOTE_TRIGGER_LABEL:
        return {"status": "ignored", "reason": f"label != {settings.QUOTE_TRIGGER_LABEL}"}

    info = get_item_columns(item_id)
    cols = info["columns"]

    amount_txt = (cv_text(cols, settings.QUOTE_AMOUNT_FORMULA_ID) or "0").strip()
    amount_ht = round(cents_from_str(amount_txt) / 100.0, 2)
    vat_rate = _read_vat_rate(cols)
    desc = (settings.DESCRIPTION_COLUMN_ID and get_formula_display_value(cols, settings.DESCRIPTION_COLUMN_ID)) or info["name"]

    vat_number = cv_text(cols, settings.VAT_NUMBER_COLUMN_ID)
    client_type = cv_text(cols, settings.CLIENT_TYPE_COLUMN_ID)
    addr = extract_address_fields(cols)

    token = get_access_token()
    client_id = create_client_if_needed(token, {
        "name": info["name"], "client_type": client_type or "", "vat_number": vat_number or "", **addr
    })
    q = create_quote(token, client_id, {"description": desc, "amount_ht": amount_ht, "vat_rate": vat_rate})
    quote_id = q.get("documentid") or q.get("quoteid") or q.get("id")
    web_url = q.get("url") or q.get("portal_url") or ""

    if web_url and settings.QUOTE_LINK_COLUMN_ID:
        set_link_in_column(item_id, settings.QUOTE_LINK_COLUMN_ID, web_url, "Devis")

    if settings.QUOTE_STATUS_COLUMN_ID and settings.QUOTE_STATUS_AFTER_CREATE:
        set_status(item_id, settings.QUOTE_STATUS_COLUMN_ID, settings.QUOTE_STATUS_AFTER_CREATE)

    return {"status": "ok", "quote": {"id": quote_id, "url": web_url}}
