import json
import logging
import re
from fastapi import FastAPI, Request, HTTPException, Query
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

app = FastAPI(title="Energyz PayPlug API", version="2.3 (webhook-debug)")


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


def _extract_status_label(value_json: dict) -> str:
    if not isinstance(value_json, dict):
        return ""
    lbl = value_json.get("label")
    if isinstance(lbl, dict):
        return str(lbl.get("text") or "").strip()
    if isinstance(lbl, str):
        return lbl.strip()
    v = value_json.get("value")
    return str(v or "").strip()


def _norm(s: str) -> str:
    return (s or "").strip().lower()


# ---------- Health ----------
@app.get("/")
def root():
    return {"status": "ok", "message": "Energyz PayPlug API is live 🚀", "version": "2.3"}


@app.get("/debug/config")
def debug_config():
    return {
        "PUBLIC_BASE_URL": getattr(settings, "PUBLIC_BASE_URL", ""),
        "NOTIFICATION_URL": getattr(settings, "NOTIFICATION_URL", None),
        "MONDAY_BOARD_ID": getattr(settings, "MONDAY_BOARD_ID", None),
        "STATUS_COLUMN_ID": getattr(settings, "STATUS_COLUMN_ID", None),
    }


# ---------- Monday -> création lien ----------
@app.post("/quote/from_monday")
async def quote_from_monday(request: Request):
    try:
        raw = await request.body()
        payload = _safe_json_loads(raw.decode("utf-8", errors="ignore"), default={}) or {}
        logger.info(f"[WEBHOOK] payload={payload}")

        event = payload.get("event") or {}
        item_id = event.get("pulseId") or event.get("itemId")
        if not item_id:
            raise HTTPException(status_code=400, detail="Item ID manquant (pulseId/itemId).")

        trigger_col = event.get("columnId")
        trigger_status_col = getattr(settings, "TRIGGER_STATUS_COLUMN_ID", "status")
        trigger_labels = _safe_json_loads(
            getattr(settings, "TRIGGER_LABELS_JSON", None),
            default={"1": "Acompte 1", "2": "Acompte 2"},
        ) or {"1": "Acompte 1", "2": "Acompte 2"}

        acompte_num = None
        if trigger_col == trigger_status_col:
            value_json = _safe_json_loads(event.get("value"), default={}) or {}
            current_label = _extract_status_label(value_json).lower()
            for k, label in trigger_labels.items():
                if current_label == str(label).lower():
                    acompte_num = k
                    break
            if acompte_num is None and "acompte" in current_label:
                acompte_num = "1" if "1" in current_label else ("2" if "2" in current_label else None)

        if acompte_num not in ("1", "2"):
            raise HTTPException(status_code=400, detail="Label status non reconnu pour acompte 1/2.")

        # Colonnes nécessaires
        formula_cols = _safe_json_loads(settings.FORMULA_COLUMN_IDS_JSON, default={}) or {}
        link_columns = _safe_json_loads(settings.LINK_COLUMN_IDS_JSON, default={}) or {}
        if acompte_num not in formula_cols or acompte_num not in link_columns:
            raise HTTPException(
                status_code=500,
                detail=f"FORMULA_COLUMN_IDS_JSON/LINK_COLUMN_IDS_JSON sans clé '{acompte_num}'.",
            )

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
        cols = get_item_columns(item_id, needed_cols)
        logger.info(f"[MONDAY] item_id={item_id} values={cols}")

        email = cols.get(settings.EMAIL_COLUMN_ID, "") or ""
        address = cols.get(settings.ADDRESS_COLUMN_ID, "") or ""
        description = cols.get(settings.DESCRIPTION_COLUMN_ID, "") or ""
        iban = (cols.get(settings.IBAN_FORMULA_COLUMN_ID, "") or "").strip()

        # ---------- Montant ----------
        formula_id = formula_cols[acompte_num]
        acompte_txt = _clean_number_text(cols.get(formula_id, ""))
        if float(acompte_txt or "0") <= 0:
            computed = compute_formula_value_for_item(formula_id, int(item_id))
            if computed is not None and computed > 0:
                acompte_txt = str(computed)

        if float(acompte_txt or "0") <= 0:
            total_ht_txt = _clean_number_text(cols.get(settings.QUOTE_AMOUNT_FORMULA_ID, "0"))
            if float(total_ht_txt) > 0:
                acompte_txt = str(float(total_ht_txt) / 2.0)
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Montant introuvable (formula + recalcul + total HT vides).",
                )

        amount_cents = cents_from_str(acompte_txt)
        if amount_cents <= 0:
            raise HTTPException(status_code=400, detail=f"Montant invalide après parsing: '{acompte_txt}'.")

        # ---------- IBAN / Clé PayPlug ----------
        forced_iban = getattr(settings, "FORCE_IBAN", "").strip()
        if forced_iban:
            iban = forced_iban
            logger.info(f"[IBAN] Using FORCE_IBAN='{iban}'")

        if not iban:
            business_col_id = getattr(settings, "BUSINESS_STATUS_COLUMN_ID", "color_mkwnxf1h")
            business_label = (cols.get(business_col_id, "") or "").strip()
            env_map = _safe_json_loads(getattr(settings, "IBAN_BY_STATUS_JSON", None), default={}) or {}
            default_map = {
                "energyz mar": "FR76 1695 8000 0130 5670 5696 366",
                "energyz divers": "FR76 1695 8000 0100 0571 1982 492",
            }
            merged = {**default_map, **{_norm(k): v for k, v in env_map.items()}}
            bl = _norm(business_label)
            chosen = ""
            for k, v in merged.items():
                if not v:
                    continue
                if bl == k or bl.startswith(k) or (k in bl):
                    chosen = v.strip()
                    break
            logger.info(f"[IBAN] business='{business_label}' → chosen='{chosen}'")
            if chosen:
                iban = chosen

        if not iban:
            raise HTTPException(status_code=400, detail="IBAN introuvable (formule + fallback BL vides).")

        api_key = _choose_api_key(iban)
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail=f"Aucune clé PayPlug mappée pour IBAN '{iban}' (mode={settings.PAYPLUG_MODE}).",
            )

        # ---------- Metadata ----------
        metadata = {
            "board_id": str(getattr(settings, "MONDAY_BOARD_ID", "")),
            "item_id": str(item_id),              # <- clé standard qu'on lit dans le webhook
            "item_name": cols.get("name", ""),
            "acompte": acompte_num,
            "description": description or f"Acompte {acompte_num}",
            "source": "energyz-monday",
        }

        # ---------- Création paiement ----------
        payment_url = create_payment(
            api_key=api_key,
            amount_cents=amount_cents,
            email=email,
            address=address,
            client_name=cols.get("name", "Client Energyz"),
            metadata=metadata,
        )

        # On met UNIQUEMENT le lien, PAS le statut (on attend le webhook PayPlug)
        set_link_in_column(item_id, link_columns[acompte_num], payment_url, f"Payer acompte {acompte_num}")

        logger.info(f"[OK-LINK] item={item_id} acompte={acompte_num} amount_cents={amount_cents} url={payment_url}")
        return {
            "status": "ok",
            "item_id": item_id,
            "acompte": acompte_num,
            "amount_cents": amount_cents,
            "payment_url": payment_url,
        }
    except HTTPException as e:
        logger.error(f"[HTTP] {e.status_code} {e.detail}")
        raise
    except Exception as e:
        logger.exception(f"[EXCEPTION] {e}")
        raise HTTPException(status_code=500, detail=f"Erreur webhook Monday : {e}")


# ---------- PayPlug -> Webhook paiement confirmé ----------
@app.post("/payplug/webhook")
async def payplug_webhook(request: Request):
    try:
        payload = await request.json()
        logger.info(f"[PP-WEBHOOK] payload={payload}")

        # --- Détection paid sur TOUS les formats connus ---
        def _get(d, path, default=None):
            cur = d
            for k in path:
                if not isinstance(cur, dict) or k not in cur:
                    return default
                cur = cur[k]
            return cur

        root_is_paid = bool(payload.get("is_paid"))
        root_status = str(payload.get("status") or "").lower()
        root_type = str(payload.get("type") or "")
        data_obj = payload.get("data") or {}
        obj = data_obj.get("object") or {}

        obj_is_paid = bool(obj.get("is_paid"))
        obj_status = str(obj.get("status") or "").lower()
        event_type = root_type

        paid_like = any([
            root_is_paid,
            obj_is_paid,
            root_status in {"paid", "succeeded"},
            obj_status in {"paid", "succeeded"},
            event_type in {"payment.succeeded", "charge.succeeded", "payment_paid"},
        ])

        if not paid_like:
            logger.info("[PP-WEBHOOK] not paid-like, ignore")
            return JSONResponse({"ok": True, "ignored": True})

        # --- Récup metadata (plusieurs emplacements possibles) ---
        metadata = {}
        for candidate in [obj.get("metadata"), data_obj.get("metadata"), payload.get("metadata")]:
            if candidate is None:
                continue
            md = candidate if isinstance(candidate, dict) else _safe_json_loads(candidate, default=None)
            if isinstance(md, dict):
                metadata = md
                break

        item_id = metadata.get("item_id") or metadata.get("customer_id")
        acompte = str(metadata.get("acompte") or "1")

        if not item_id:
            logger.error("[PP-WEBHOOK] metadata sans item_id/customer_id → rien à MAJ")
            return JSONResponse({"ok": False, "error": "no_item_id"}, status_code=200)

        status_after = _safe_json_loads(settings.STATUS_AFTER_PAY_JSON, default={}) or {}
        next_status = status_after.get(acompte, f"Payé acompte {acompte}")

        try:
            set_status(int(item_id), settings.STATUS_COLUMN_ID, next_status)
            logger.info(f"[PP-WEBHOOK] set_status OK item_id={item_id} -> '{next_status}'")
            return JSONResponse({"ok": True})
        except Exception as e:
            logger.exception(f"[PP-WEBHOOK] set_status FAILED item_id={item_id}: {e}")
            return JSONResponse({"ok": False, "error": "monday_update_failed"}, status_code=200)

    except Exception as e:
        logger.exception(f"[PP-WEBHOOK] EXCEPTION {e}")
        return JSONResponse({"ok": False}, status_code=200)


# ---------- DEBUG: simuler un paiement PayPlug 'paid' ----------
@app.get("/debug/mock_paid")
def debug_mock_paid(
    item_id: int = Query(..., description="ID de l'item Monday"),
    acompte: int = Query(1, description="Numéro d'acompte 1/2")
):
    try:
        status_after = _safe_json_loads(settings.STATUS_AFTER_PAY_JSON, default={}) or {}
        next_status = status_after.get(str(acompte), f"Payé acompte {acompte}")
        set_status(int(item_id), settings.STATUS_COLUMN_ID, next_status)
        return {"ok": True, "item_id": item_id, "acompte": acompte, "set_to": next_status}
    except Exception as e:
        logger.exception(f"[DEBUG] mock_paid failed: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ---------- DEBUG: coller un payload PayPlug tel quel ----------
@app.post("/debug/raw_webhook")
async def debug_raw_webhook(request: Request):
    payload = await request.json()
    logger.info(f"[DEBUG-RAW] payload={payload}")
    # On réutilise le même handler, en l'appelant "à la main"
    req = request
    req._body = json.dumps(payload).encode("utf-8")
    return await payplug_webhook(req)
