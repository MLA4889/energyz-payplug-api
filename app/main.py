import json
import logging
import os
import re
import requests
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse
from .config import settings
from .payments import _choose_api_key, cents_from_str, create_payment
from . import monday as m

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("energyz")

app = FastAPI(title="Energyz PayPlug API", version="3.0 (notification_url + webhook stable)")


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


# ---------- Root ----------
@app.get("/")
def root():
    return {"status": "ok", "service": "energyz-payplug-api", "version": app.version}


# ---------- Création lien depuis Monday ----------
@app.post("/quote/from_monday")
async def quote_from_monday(request: Request):
    try:
        raw = await request.body()
        payload = _safe_json_loads(raw.decode("utf-8", errors="ignore"), default={}) or {}
        logger.info(f"[WEBHOOK] payload={payload}")

        event = payload.get("event") or {}
        item_id = event.get("pulseId") or event.get("itemId")
        if not item_id:
            raise HTTPException(status_code=400, detail="Item ID manquant")

        trigger_labels = _safe_json_loads(
            getattr(settings, "TRIGGER_LABELS_JSON", None),
            default={"1": "Générer acompte 1", "2": "Générer acompte 2"},
        )
        trigger_col = event.get("columnId")
        trigger_status_col = getattr(settings, "TRIGGER_STATUS_COLUMN_ID", "status")
        acompte_num = None
        if trigger_col == trigger_status_col:
            val_json = _safe_json_loads(event.get("value"), default={}) or {}
            lbl = str(val_json.get("label") or "").lower()
            for k, v in trigger_labels.items():
                if lbl == str(v).lower():
                    acompte_num = k
                    break
        if acompte_num not in ("1", "2"):
            raise HTTPException(status_code=400, detail="Label non reconnu pour acompte")

        formula_cols = _safe_json_loads(settings.FORMULA_COLUMN_IDS_JSON, default={}) or {}
        link_cols = _safe_json_loads(settings.LINK_COLUMN_IDS_JSON, default={}) or {}
        if acompte_num not in formula_cols or acompte_num not in link_cols:
            raise HTTPException(status_code=500, detail="Colonnes manquantes")

        needed_cols = [
            settings.EMAIL_COLUMN_ID,
            settings.ADDRESS_COLUMN_ID,
            settings.DESCRIPTION_COLUMN_ID,
            settings.IBAN_FORMULA_COLUMN_ID,
            settings.QUOTE_AMOUNT_FORMULA_ID,
            formula_cols[acompte_num],
            getattr(settings, "BUSINESS_STATUS_COLUMN_ID", "color_mkwnxf1h"),
            "name",
        ]
        cols = m.get_item_columns(item_id, needed_cols)
        email = cols.get(settings.EMAIL_COLUMN_ID, "")
        description = cols.get(settings.DESCRIPTION_COLUMN_ID, "")
        item_name = cols.get("name", "")
        acompte_txt = cols.get(formula_cols[acompte_num], "")
        amount_cents = cents_from_str(acompte_txt)

        iban = cols.get(settings.IBAN_FORMULA_COLUMN_ID, "").strip()
        api_key = _choose_api_key(iban)
        if not api_key:
            raise HTTPException(status_code=400, detail="Clé PayPlug introuvable")

        # Crée le paiement
        desc = f"{item_name} — Acompte {acompte_num}"
        metadata = {"item_id": str(item_id), "acompte": acompte_num, "description": desc}
        pp_data = create_payment(api_key, amount_cents, email, None, item_name, metadata)

        payment_url = (pp_data.get("hosted_payment") or {}).get("payment_url")
        payment_id = pp_data.get("id")

        m.set_link_in_column(item_id, link_cols[acompte_num], payment_url, f"Payer acompte {acompte_num}")
        logger.info(f"[PAYMENT] item={item_id} acompte={acompte_num} url={payment_url} id={payment_id}")

        return {"ok": True, "payment_url": payment_url, "payment_id": payment_id}

    except Exception as e:
        logger.exception(f"[ERROR] {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Webhook PayPlug ----------
@app.post("/payplug/webhook")
async def payplug_webhook(request: Request):
    try:
        payload = await request.json()
        logger.info(f"[PP-WEBHOOK] raw={payload}")

        event_type = payload.get("type") or ""
        data = payload.get("data", {})
        obj = data.get("object", {})
        meta = obj.get("metadata", {})

        item_id = meta.get("item_id")
        acompte = meta.get("acompte")

        if not item_id:
            return {"ok": False, "error": "missing_item_id"}

        status = (obj.get("status") or "").lower()
        is_paid = bool(obj.get("is_paid") or obj.get("paid"))
        if event_type == "payment.succeeded" or status == "paid" or is_paid:
            status_after = _safe_json_loads(getattr(settings, "STATUS_AFTER_PAY_JSON", None), default={}) or {}
            label = status_after.get(acompte, f"Payé acompte {acompte}")
            from .main import _set_status_force  # type: ignore
            _set_status_force(int(item_id), getattr(settings, "STATUS_COLUMN_ID", "status"), label)
            logger.info(f"[PP-WEBHOOK] ✅ Statut mis à jour : {item_id} → {label}")
            return {"ok": True}

        logger.info(f"[PP-WEBHOOK] Ignored event: {event_type} status={status}")
        return {"ok": True, "ignored": True}

    except Exception as e:
        logger.exception(f"[PP-WEBHOOK] error {e}")
        return {"ok": False, "error": str(e)}


# ---------- Endpoint test manuel ----------
@app.get("/payplug/mark_paid")
def mark_paid(item_id: int, acompte: str, token: str = Query(...)):
    admin_token = (os.getenv("ADMIN_HOOK_TOKEN") or "").strip()
    if not admin_token or token != admin_token:
        raise HTTPException(status_code=403, detail="Forbidden")

    status_after = _safe_json_loads(getattr(settings, "STATUS_AFTER_PAY_JSON", None), default={}) or {}
    label = status_after.get(acompte, f"Payé acompte {acompte}")
    from .main import _set_status_force  # type: ignore
    _set_status_force(int(item_id), getattr(settings, "STATUS_COLUMN_ID", "status"), label)
    return {"ok": True, "item_id": item_id, "acompte": acompte, "label": label}
