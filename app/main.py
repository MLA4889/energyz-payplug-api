from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from typing import Any, Optional

import payplug

from .config import settings
from .monday import (
    get_item_columns,
    extract_display_number,
    extract_display_text,
    get_status_label,
    set_link_in_column,
    set_status,
    upload_file_to_column,
)
from .payments import _choose_api_key, cents_from_str, create_payment, normalize_iban
from .evoliz import get_access_token, create_client_if_needed, create_quote, create_invoice, fetch_pdf


app = FastAPI(title=f"{settings.BRAND_NAME} PayPlug/Evoliz Bridge")


# --- Health checks ---
@app.get("/")
def root():
    return {"status": "ok", "brand": settings.BRAND_NAME}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "brand": settings.BRAND_NAME,
        "payplug_mode": settings.PAYPLUG_MODE,
        "board_id": settings.MONDAY_BOARD_ID,
        "public_base_url": settings.PUBLIC_BASE_URL
    }


# --- Helpers lecture Monday item ---
def _read_common_from_monday(item_id: int) -> dict:
    cols = get_item_columns(item_id)

    business_label = get_status_label(cols, settings.BUSINESS_STATUS_COLUMN_ID) or ""
    name = cols.get("name", {}).get("text") or f"Item {item_id}"

    # Adresse
    address_text = extract_display_text(cols.get(settings.ADDRESS_COLUMN_ID)) or ""

    # Description presta
    description = extract_display_text(cols.get(settings.DESCRIPTION_COLUMN_ID)) or name

    # TVA (nombre), fallback DEFAULT_VAT_RATE
    vat_rate = extract_display_number(cols.get(settings.VAT_RATE_COLUMN_ID))
    vat_rate = float(vat_rate) if vat_rate is not None else float(settings.DEFAULT_VAT_RATE)

    # Client type
    client_type = get_status_label(cols, settings.CLIENT_TYPE_COLUMN_ID) or "Particulier"
    vat_number = extract_display_text(cols.get(settings.VAT_NUMBER_COLUMN_ID)) or ""

    # Total HT pour devis
    total_ht = extract_display_number(cols.get(settings.QUOTE_AMOUNT_FORMULA_ID)) or 0.0

    # IBAN via formula puis fallback statut
    iban_formula_text = extract_display_text(cols.get(settings.IBAN_FORMULA_COLUMN_ID))
    iban = iban_formula_text or settings.PAYPLUG_IBAN_BY_STATUS.get(business_label, "")
    iban = normalize_iban(iban) or ""

    return {
        "cols": cols,
        "business_label": business_label,
        "name": name,
        "address": address_text,
        "description": description,
        "vat_rate": vat_rate,
        "client_type": client_type,
        "vat_number": vat_number,
        "total_ht": float(total_ht),
        "iban": iban,
    }


def _read_acompte_amount(n: str, cols: dict, business_label: str) -> float:
    """
    1) essaie la colonne formula correspondante
    2) sinon fallback via ACOMPTE_AMOUNTS_JSON
    """
    col_id = settings.FORMULA_COLUMN_IDS.get(str(n))
    amt = None
    if col_id:
        amt = extract_display_number(cols.get(col_id))
    if amt is None:
        # fallback
        fallback_map = settings.ACOMPTE_AMOUNTS.get(str(n), {})
        val = fallback_map.get(business_label)
        if val is not None:
            amt = float(val)
    return float(amt or 0.0)


# --- Debug: Evoliz ---
@app.get("/debug/evoliz/login")
def debug_evoliz_login():
    try:
        token = get_access_token()
        return {"status": "ok", "token_preview": (token[:6] + "..." if token else "")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Debug: quote preview ---
@app.get("/debug/quote/preview/{item_id}")
def debug_quote_preview(item_id: int):
    info = _read_common_from_monday(item_id)
    return {
        "item_id": item_id,
        "business": info["business_label"],
        "iban": info["iban"],
        "description": info["description"],
        "vat_rate": info["vat_rate"],
        "client_type": info["client_type"],
        "vat_number": info["vat_number"],
        "total_ht": info["total_ht"],
    }


# --- Debug: PayPlug ---
@app.get("/debug/payplug/{item_id}")
def debug_payplug(item_id: int):
    info = _read_common_from_monday(item_id)
    key = _choose_api_key(info["iban"])
    return {
        "item_id": item_id,
        "business": info["business_label"],
        "iban_raw": info["iban"],
        "mode": settings.PAYPLUG_MODE,
        "keys_available": {
            "test_has_any": bool(settings.PAYPLUG_KEYS_TEST),
            "live_has_any": bool(settings.PAYPLUG_KEYS_LIVE),
        },
        "selected_key_is_set": bool(key),
    }


# --- PayPlug: lien acompte ---
@app.api_route("/pay/acompte/{n}", methods=["GET", "POST"])
def pay_acompte(n: int, item_id: int = Query(..., description="Monday item_id")):
    if str(n) not in settings.FORMULA_COLUMN_IDS and str(n) not in settings.ACOMPTE_AMOUNTS:
        raise HTTPException(status_code=400, detail=f"Acompte {n} non configuré")

    info = _read_common_from_monday(item_id)

    # IBAN -> clé PayPlug (ou fallback via statut)
    api_key = _choose_api_key(info["iban"])
    if not api_key:
        raise HTTPException(status_code=400, detail="Aucune clé PayPlug correspondante à l'IBAN sélectionné")

    payplug.set_secret_key(api_key)

    # Montant acompte
    amount_ht = _read_acompte_amount(str(n), info["cols"], info["business_label"])
    if amount_ht <= 0:
        raise HTTPException(status_code=400, detail=f"Montant d'acompte {n} invalide (valeur lue '{amount_ht}')")

    amount_cents = cents_from_str(amount_ht)
    return_url = f"{settings.PUBLIC_BASE_URL}/pay/return?item_id={item_id}&n={n}"
    description = f"{settings.BRAND_NAME} - Acompte {n} - {info['name']}"

    try:
        payment = create_payment(amount_cents, description, return_url)
    except payplug.exceptions.SecretKeyNotSet:
        raise HTTPException(status_code=500, detail="payplug.exceptions.SecretKeyNotSet")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Ecrit le lien dans la colonne adéquate si configurée
    link_col = settings.LINK_COLUMN_IDS.get(str(n), "")
    if link_col:
        try:
            set_link_in_column(item_id, link_col, payment.hosted_payment.payment_url, f"Lien acompte {n}")
        except Exception:
            pass

    # Option: statut après paiement (à gérer via webhook PayPlug si tu veux l'automatiser)
    return {"status": "ok", "payment": {"url": payment.hosted_payment.payment_url}}


# --- Webhook: Générer devis ---
@app.post("/quote/from_monday")
def quote_from_monday(req: Request):
    payload = {}
    try:
        payload = req.json() if hasattr(req, "json") else {}
    except Exception:
        payload = {}

    # Monday envoie {event: {pulseId: "...", columnId: "...", value: "...", ...}}
    body = payload or {}
    event = body.get("event", {})
    item_id = int(event.get("pulseId") or event.get("itemId") or 0)
    if not item_id:
        # Permet d'appeler manuellement sans webhook: ?item_id=...
        item_id = int(req.query_params.get("item_id", "0"))
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id manquant")

    info = _read_common_from_monday(item_id)

    # Vérifie que le label correspond bien au trigger
    label = get_status_label(info["cols"], settings.QUOTE_STATUS_COLUMN_ID) or ""
    if settings.QUOTE_TRIGGER_LABEL and label != settings.QUOTE_TRIGGER_LABEL:
        # on ne bloque pas, mais on informe
        pass

    # Evoliz
    try:
        token = get_access_token()
        client_id = create_client_if_needed(token, {
            "name": info["name"],
            "client_type": info["client_type"],
            "address": info["address"],
            "postcode": "",  # optionnel si colonnes spécifiques pas remplies
            "city": "",
            "vat_number": info["vat_number"],
        })
        qdata = create_quote(token, client_id, {
            "description": info["description"],
            "amount_ht": info["total_ht"],
            "vat_rate": info["vat_rate"],
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evoliz: {e}")

    # Lien document (webdoc) si présent dans la réponse
    # Selon Evoliz, on peut avoir "web" ou il faut composer l'URL. Par sécurité, on set au moins un lien interne.
    quote_id = int(qdata.get("quoteid") or qdata.get("id") or 0)
    quote_url = qdata.get("url") or qdata.get("public_link") or ""
    if not quote_url:
        quote_url = f"https://app.evoliz.com/companies/{settings.EVOLIZ_COMPANY_ID}/quotes/{quote_id}"

    # Ecrit lien + status
    try:
        set_link_in_column(item_id, settings.QUOTE_LINK_COLUMN_ID, quote_url, "Devis Evoliz")
    except Exception:
        pass

    if settings.QUOTE_STATUS_AFTER_CREATE:
        try:
            set_status(item_id, settings.QUOTE_STATUS_COLUMN_ID, settings.QUOTE_STATUS_AFTER_CREATE)
        except Exception:
            pass

    # Upload PDF si dispo
    try:
        pdf = fetch_pdf(token, "quotes", quote_id)
        if pdf:
            content, filename = pdf
            upload_file_to_column(item_id, settings.QUOTE_FILES_COLUMN_ID, filename, content)
    except Exception:
        pass

    return {"status": "ok", "quote_id": quote_id, "url": quote_url}


# --- Webhook: Facturer (acompte 1/2/solde) ---
@app.post("/invoice/from_monday")
def invoice_from_monday(req: Request):
    payload = {}
    try:
        payload = req.json() if hasattr(req, "json") else {}
    except Exception:
        payload = {}

    body = payload or {}
    event = body.get("event", {})
    item_id = int(event.get("pulseId") or event.get("itemId") or 0)
    if not item_id:
        item_id = int(req.query_params.get("item_id", "0"))
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id manquant")

    info = _read_common_from_monday(item_id)
    label = get_status_label(info["cols"], settings.QUOTE_STATUS_COLUMN_ID) or ""

    # Détermine le type de facture demandé
    inv_type = None
    if label == settings.INVOICE_LABEL_ACOMPTE1:
        inv_type = "AC1"
        amt_ht = _read_acompte_amount("1", info["cols"], info["business_label"])
        link_col = settings.INVOICE_LINK_AC1_COLUMN_ID
    elif label == settings.INVOICE_LABEL_ACOMPTE2:
        inv_type = "AC2"
        amt_ht = _read_acompte_amount("2", info["cols"], info["business_label"])
        link_col = settings.INVOICE_LINK_AC2_COLUMN_ID
    elif label == settings.INVOICE_LABEL_SOLDE:
        inv_type = "SOLDE"
        ac1 = _read_acompte_amount("1", info["cols"], info["business_label"])
        ac2 = _read_acompte_amount("2", info["cols"], info["business_label"])
        amt_ht = max(info["total_ht"] - ac1 - ac2, 0.0)
        link_col = settings.INVOICE_LINK_FINAL_COLUMN_ID
    else:
        raise HTTPException(status_code=400, detail=f"Label de statut inattendu: {label}")

    if amt_ht <= 0:
        raise HTTPException(status_code=400, detail=f"Montant HT invalide pour {inv_type}: {amt_ht}")

    # Evoliz
    try:
        token = get_access_token()
        client_id = create_client_if_needed(token, {
            "name": info["name"],
            "client_type": info["client_type"],
            "address": info["address"],
            "postcode": "",
            "city": "",
            "vat_number": info["vat_number"],
        })
        idata = create_invoice(token, client_id, {
            "description": f"{info['description']} - {inv_type}",
            "amount_ht": amt_ht,
            "vat_rate": info["vat_rate"],
            "paytermid": settings.EVOLIZ_PAYTERM_ID,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evoliz: {e}")

    invoice_id = int(idata.get("invoiceid") or idata.get("id") or 0)
    invoice_url = idata.get("url") or idata.get("public_link") or ""
    if not invoice_url:
        invoice_url = f"https://app.evoliz.com/companies/{settings.EVOLIZ_COMPANY_ID}/invoices/{invoice_id}"

    # Ecrit lien + upload PDF
    try:
        if link_col:
            set_link_in_column(item_id, link_col, invoice_url, f"Facture {inv_type}")
    except Exception:
        pass

    try:
        pdf = fetch_pdf(token, "invoices", invoice_id)
        if pdf:
            content, filename = pdf
            files_col = settings.INVOICE_FILES_COLUMN_ID or settings.QUOTE_FILES_COLUMN_ID
            upload_file_to_column(item_id, files_col, filename, content)
    except Exception:
        pass

    return {"status": "ok", "invoice_id": invoice_id, "url": invoice_url}
