from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from fastapi import Body, FastAPI, HTTPException, Request
import requests

from .config import settings
from .monday import (
    get_item_columns,
    get_formula_display_value,
    set_link_in_column,
    set_status,
    extract_address_fields,
    upload_file_to_files_column,
)
from .payments import create_payment, cents_from_str
from .evoliz import get_access_token, create_client_if_needed, create_quote, create_invoice

app = FastAPI(title=f"{settings.BRAND_NAME} PayPlug & Evoliz API")


def _target_files_col() -> str:
    return settings.DOC_FILES_COLUMN_ID or settings.INVOICE_FILES_COLUMN_ID or settings.QUOTE_FILES_COLUMN_ID


@app.get("/")
def root():
    return {"status": "ok", "brand": settings.BRAND_NAME}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "brand": settings.BRAND_NAME,
        "board": settings.MONDAY_BOARD_ID,
        "payplug_mode": settings.PAYPLUG_MODE,
        "files_col": _target_files_col(),
        "evoliz_company": settings.EVOLIZ_COMPANY_ID,
    }


# ------------------ DEBUG ------------------

@app.get("/debug/evoliz/login")
def debug_evoliz_login():
    token = get_access_token()
    return {"status": "ok", "token_preview": token[:12] + "..."}


@app.get("/debug/quote/preview/{item_id}")
def debug_quote_preview(item_id: int):
    info = get_item_columns(item_id)
    cols = info["columns"]

    amount_ht_txt = (cols.get(settings.QUOTE_AMOUNT_FORMULA_ID, {}) or {}).get("text") or "0"
    vat_rate_txt = (cols.get(settings.VAT_RATE_COLUMN_ID, {}) or {}).get("text") or str(settings.DEFAULT_VAT_RATE)
    desc = (settings.DESCRIPTION_COLUMN_ID and get_formula_display_value(cols, settings.DESCRIPTION_COLUMN_ID)) or info["name"]
    vat_number = cols.get(settings.VAT_NUMBER_COLUMN_ID, {}).get("text") if settings.VAT_NUMBER_COLUMN_ID else None

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
    iban_txt = (settings.IBAN_FORMULA_COLUMN_ID and get_formula_display_value(cols, settings.IBAN_FORMULA_COLUMN_ID)) or ""
    mode = settings.PAYPLUG_MODE
    keys = list((settings.PAYPLUG_KEYS_LIVE if mode == "live" else settings.PAYPLUG_KEYS_TEST).keys())
    return {"item_id": item_id, "iban_raw": iban_txt, "mode": mode, "keys_available": keys}


# ------------------ PayPlug (acompte) ------------------

@app.api_route("/pay/acompte/{n}", methods=["GET", "POST"])
async def pay_acompte(n: int, item_id: Optional[int] = None, request: Request = None):
    # lecture item_id depuis webhook Monday si POST
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

    # montant depuis FORMULA_COLUMN_IDS[n]
    formula_col_id = settings.FORMULA_COLUMN_IDS.get(str(n))
    if not formula_col_id:
        raise HTTPException(400, f"FORMULA_COLUMN_IDS n°{n} non configurée")
    amount_txt = get_formula_display_value(cols, formula_col_id) or ""
    amount_cents = cents_from_str(amount_txt)
    if amount_cents <= 0:
        raise HTTPException(400, f"Montant d'acompte {n} invalide pour l'item {item_id} (valeur lue='{amount_txt or '0'}'). Mets un nombre > 0 dans la colonne formule.")

    # description + IBAN
    desc = (settings.DESCRIPTION_COLUMN_ID and get_formula_display_value(cols, settings.DESCRIPTION_COLUMN_ID)) or info["name"]
    iban_txt = (settings.IBAN_FORMULA_COLUMN_ID and get_formula_display_value(cols, settings.IBAN_FORMULA_COLUMN_ID)) or ""

    pay = create_payment(amount_cents, f"Acompte {n} – {desc}", f"{settings.PUBLIC_BASE_URL}/", iban_txt)

    link_col = settings.LINK_COLUMN_IDS.get(str(n))
    if link_col:
        set_link_in_column(item_id, link_col, pay["url"], f"Payer acompte {n}")

    # statut post-paiement (optionnel – serait plutôt dans un webhook IPN)
    if settings.STATUS_COLUMN_ID and settings.STATUS_AFTER_PAY.get(str(n)):
        try:
            set_status(item_id, settings.STATUS_COLUMN_ID, settings.STATUS_AFTER_PAY[str(n)])
        except Exception:
            pass

    return {"status": "ok", "payment": pay}


# ------------------ helpers devis/factures ------------------

def _read_vat_rate(cols: Dict[str, Any]) -> float:
    txt = cols.get(settings.VAT_RATE_COLUMN_ID, {}).get("text") if settings.VAT_RATE_COLUMN_ID else None
    if not txt:
        return settings.DEFAULT_VAT_RATE
    try:
        return float(txt.replace(",", "."))
    except Exception:
        return settings.DEFAULT_VAT_RATE


def _download_evoliz_pdf(token: str, kind: str, document_id: int) -> Optional[bytes]:
    try:
        url = f"{settings.EVOLIZ_BASE_URL}/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/{kind}/{document_id}/pdf"
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
        r.raise_for_status()
        if r.headers.get("content-type", "").lower().startswith("application/pdf"):
            return r.content
    except Exception:
        pass
    return None


# ------------------ Devis ------------------

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

    amount_txt = (cols.get(settings.QUOTE_AMOUNT_FORMULA_ID, {}) or {}).get("text") or "0"
    amount_ht = round(cents_from_str(amount_txt) / 100.0, 2)
    if amount_ht <= 0:
        raise HTTPException(400, f"Montant HT invalide (lu='{amount_txt}').")
    vat_rate = _read_vat_rate(cols)
    desc = (settings.DESCRIPTION_COLUMN_ID and get_formula_display_value(cols, settings.DESCRIPTION_COLUMN_ID)) or info["name"]

    vat_number = cols.get(settings.VAT_NUMBER_COLUMN_ID, {}).get("text") if settings.VAT_NUMBER_COLUMN_ID else None
    client_type = cols.get(settings.CLIENT_TYPE_COLUMN_ID, {}).get("text") if settings.CLIENT_TYPE_COLUMN_ID else None
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

    pdf = quote_id and _download_evoliz_pdf(token, "quotes", int(quote_id))
    files_col = _target_files_col()
    if pdf and files_col:
        upload_file_to_files_column(item_id, files_col, f"Devis_{quote_id}.pdf", pdf)

    if settings.QUOTE_STATUS_COLUMN_ID and settings.QUOTE_STATUS_AFTER_CREATE:
        set_status(item_id, settings.QUOTE_STATUS_COLUMN_ID, settings.QUOTE_STATUS_AFTER_CREATE)

    return {"status": "ok", "quote": {"id": quote_id, "url": web_url}}


# ------------------ Factures ------------------

def _compute_invoice_amount(cols: Dict[str, Any], kind: str) -> float:
    total_txt = cols.get(settings.QUOTE_AMOUNT_FORMULA_ID, {}).get("text") or "0"
    ac1_txt = settings.FORMULA_COLUMN_IDS.get("1") and get_formula_display_value(cols, settings.FORMULA_COLUMN_IDS["1"]) or "0"
    ac2_txt = settings.FORMULA_COLUMN_IDS.get("2") and get_formula_display_value(cols, settings.FORMULA_COLUMN_IDS["2"]) or "0"
    total = cents_from_str(total_txt) / 100.0
    ac1 = cents_from_str(ac1_txt) / 100.0
    ac2 = cents_from_str(ac2_txt) / 100.0
    if kind == "ac1":
        return round(ac1, 2)
    if kind == "ac2":
        return round(ac2, 2)
    return round(max(total - ac1 - ac2, 0.0), 2)


def _label_to_kind(label: str) -> Optional[str]:
    if label == settings.INVOICE_LABEL_ACOMPTE1: return "ac1"
    if label == settings.INVOICE_LABEL_ACOMPTE2: return "ac2"
    if label == settings.INVOICE_LABEL_SOLDE:    return "solde"
    return None


def _invoice_link_column_id(kind: str) -> Optional[str]:
    if kind == "ac1": return settings.INVOICE_LINK_AC1_COLUMN_ID or None
    if kind == "ac2": return settings.INVOICE_LINK_AC2_COLUMN_ID or None
    if kind == "solde": return settings.INVOICE_LINK_FINAL_COLUMN_ID or None
    return None


@app.post("/invoice/from_monday")
async def invoice_from_monday(payload: dict = Body(...)):
    try:
        item_id = int(payload["event"]["pulseId"])
    except Exception:
        raise HTTPException(400, "payload sans item_id")

    label = payload.get("event", {}).get("value", "")
    kind = _label_to_kind(label)
    if not kind:
        return {"status": "ignored", "reason": f"label {label} non géré"}

    info = get_item_columns(item_id)
    cols = info["columns"]

    amount_ht = _compute_invoice_amount(cols, kind)
    if amount_ht <= 0:
        raise HTTPException(400, f"Montant HT nul pour {kind}")

    vat_rate = _read_vat_rate(cols)
    desc = (settings.DESCRIPTION_COLUMN_ID and get_formula_display_value(cols, settings.DESCRIPTION_COLUMN_ID)) or info["name"]

    vat_number = cols.get(settings.VAT_NUMBER_COLUMN_ID, {}).get("text") if settings.VAT_NUMBER_COLUMN_ID else None
    client_type = cols.get(settings.CLIENT_TYPE_COLUMN_ID, {}).get("text") if settings.CLIENT_TYPE_COLUMN_ID else None
    addr = extract_address_fields(cols)

    token = get_access_token()
    client_id = create_client_if_needed(token, {
        "name": info["name"], "client_type": client_type or "", "vat_number": vat_number or "", **addr
    })

    inv = create_invoice(token, client_id, {
        "description": f"{desc} – {'Acompte 1' if kind=='ac1' else 'Acompte 2' if kind=='ac2' else 'Solde'}",
        "amount_ht": amount_ht,
        "vat_rate": vat_rate,
        "paytermid": settings.EVOLIZ_PAYTERM_ID,
        "documentdate": date.today().isoformat(),
    })
    invoice_id = inv.get("documentid") or inv.get("invoiceid") or inv.get("id")
    web_url = inv.get("url") or inv.get("portal_url") or ""

    link_col = _invoice_link_column_id(kind)
    if link_col and web_url:
        set_link_in_column(item_id, link_col, web_url, f"Facture {kind}")

    pdf = invoice_id and _download_evoliz_pdf(token, "invoices", int(invoice_id))
    files_col = _target_files_col()
    if pdf and files_col:
        upload_file_to_files_column(item_id, files_col, f"Facture_{invoice_id}.pdf", pdf)

    return {"status": "ok", "invoice": {"id": invoice_id, "url": web_url, "kind": kind}}
