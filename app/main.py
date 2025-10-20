import json
import logging
import re
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from .config import settings
from .payments import _choose_api_key, cents_from_str, create_payment
from .monday import (
    get_item_columns,
    set_link_in_column,
    set_status,
    compute_formula_value_for_item,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("energyz")

app = FastAPI(title="Energyz PayPlug API", version="2.0 (original restored + webhook statut)")

# ---------- Utils ----------
def _safe_json_loads(s, default=None):
    if s is None:
        return default
    if isinstance(s, dict):
        return s
    try:
        return json.loads(s)
    except Exception:
        return default

def _clean_number_text(s: str) -> str:
    if not s:
        return "0"
    s = s.replace("\u202f", "").replace(" ", "").replace("€", "").strip()
    s = s.replace(",", ".")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    return m.group(0) if m else "0"

# ---------- Health ----------
@app.get("/")
def root():
    return {"status": "ok", "message": "Energyz PayPlug API is live 🚀"}

# ---------- Création du lien depuis Monday ----------
@app.post("/quote/from_monday")
async def quote_from_monday(request: Request):
    try:
        raw = await request.body()
        payload = _safe_json_loads(raw.decode("utf-8", errors="ignore"), default={}) or {}
        event = payload.get("event") or {}
        item_id = event.get("pulseId") or event.get("itemId")
        if not item_id:
            raise HTTPException(status_code=400, detail="Item ID manquant.")

        # Lecture des colonnes nécessaires
        formula_cols = _safe_json_loads(settings.FORMULA_COLUMN_IDS_JSON, default={}) or {}
        link_columns = _safe_json_loads(settings.LINK_COLUMN_IDS_JSON, default={}) or {}
        acompte_num = "1" if "acompte 1" in json.dumps(event).lower() else "2"
        formula_id = formula_cols.get(acompte_num)
        link_col = link_columns.get(acompte_num)

        cols = get_item_columns(item_id, [
            settings.EMAIL_COLUMN_ID,
            settings.ADDRESS_COLUMN_ID,
            settings.DESCRIPTION_COLUMN_ID,
            settings.IBAN_FORMULA_COLUMN_ID,
            settings.QUOTE_AMOUNT_FORMULA_ID,
            formula_id,
            "name"
        ])

        email = cols.get(settings.EMAIL_COLUMN_ID, "")
        address = cols.get(settings.ADDRESS_COLUMN_ID, "")
        description = cols.get(settings.DESCRIPTION_COLUMN_ID, "")
        iban = (cols.get(settings.IBAN_FORMULA_COLUMN_ID, "") or "").strip()
        montant_txt = _clean_number_text(cols.get(formula_id, "0"))
        amount_cents = cents_from_str(montant_txt)

        api_key = _choose_api_key(iban)
        metadata = {
            "board_id": str(settings.MONDAY_BOARD_ID),
            "item_id": str(item_id),
            "acompte": acompte_num,
            "description": description or f"Acompte {acompte_num}"
        }

        payment_url = create_payment(api_key, amount_cents, email, address, cols.get("name", ""), metadata)
        set_link_in_column(item_id, link_col, payment_url, f"Payer acompte {acompte_num}")

        return {"status": "ok", "url": payment_url}

    except Exception as e:
        logger.exception(f"[EXCEPTION] {e}")
        raise HTTPException(status_code=500, detail=f"Erreur: {e}")

# ---------- PayPlug → maj statut "Payé acompte X" ----------
@app.post("/payplug/webhook")
async def payplug_webhook(request: Request):
    try:
        payload = await request.json()
        logger.info(f"[PP-WEBHOOK] payload={payload}")

        event_type = payload.get("type")
        data = payload.get("data") or {}
        payment = data.get("object") or data
        metadata = _safe_json_loads(payment.get("metadata"), default={}) or {}

        status = (payment.get("status") or "").lower()
        is_paid_flag = bool(payment.get("is_paid"))
        paid_like = event_type in {"payment.succeeded", "charge.succeeded"} or status == "paid" or is_paid_flag

        if not paid_like:
            return JSONResponse({"ok": True, "ignored": True})

        item_id = metadata.get("item_id")
        acompte = metadata.get("acompte")
        if item_id and acompte:
            next_status = f"Payé acompte {acompte}"
            set_status(int(item_id), settings.STATUS_COLUMN_ID, next_status)
            logger.info(f"[PP-WEBHOOK] statut mis à jour: {item_id} -> {next_status}")

        return JSONResponse({"ok": True})

    except Exception as e:
        logger.exception(f"[PP-WEBHOOK] erreur {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=200)
