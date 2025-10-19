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

app = FastAPI(title="Energyz PayPlug API", version="2.1 (robust IBAN + PP webhook)")


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
    return {"status": "ok", "message": "Energyz PayPlug API is live 🚀"}


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

        # ---------- IBAN : 3 niveaux de fallback ----------
        # 0) IBAN forcé (si présent dans l'env) : FORCE_IBAN
        forced_iban = getattr(settings, "FORCE_IBAN", "").strip()
        if forced_iban:
            iban = forced_iban
            logger.info(f"[IBAN] Using FORCE_IBAN='{iban}'")

        # 1) Si formule vide, on tente un mapping par Business Line (avec normalisation et matching souple)
        if not iban:
            business_col_id = getattr(settings, "BUSINESS_STATUS_COLUMN_ID", "color_mkwnxf1h")
            business_label = (cols.get(business_col_id, "") or "").strip()

            # mapping depuis l'env (clé: label BL, valeur: IBAN) + défauts codés
            env_map = _safe_json_loads(getattr(settings, "IBAN_BY_STATUS_JSON", None), default={}) or {}
            default_map = {
                # défauts utiles si ton env est vide/incomplet
                "energyz mar":    "FR76 1695 8000 0130 5670 5696 366",
                "energyz divers": "FR76 1695 8000 0100 0571 1982 492",
            }
            # merge : l'env écrase les défauts
            # (on normalise les clés ici pour matcher en minuscule partout)
            merged = {**default_map, **{_norm(k): v for k, v in env_map.items()}}

            bl = _norm(business_label)
            chosen = ""
            tried = []
            for k, v in merged.items():
                tried.append(k)
                if not v:
                    continue
                # match exact / startswith / contains
                if bl == k or bl.startswith(k) or (k in bl):
                    chosen = v.strip()
                    break

            logger.info(f"[IBAN] business_label='{business_label}' (norm='{bl}') tried={tried} → chosen='{chosen}'")
            if chosen:
                iban = chosen

        if not iban:
            raise HTTPException(
                status_code=400,
                detail="IBAN introuvable (formule vide + pas de fallback Business Line).",
            )

        # ---------- Clé PayPlug ----------
        api_key = _choose_api_key(iban)
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail=f"Aucune clé PayPlug mappée pour IBAN '{iban}' (mode={settings.PAYPLUG_MODE}).",
            )

        # ---------- Metadata riche ----------
        metadata = {
            "board_id": str(getattr(settings, "MONDAY_BOARD_ID", "")),
            "item_id": str(item_id),
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

        set_link_in_column(item_id, link_columns[acompte_num], payment_url, f"Payer acompte {acompte_num}")

        # Tu peux laisser le statut tel quel et le passer à "Payé ..." via webhook PayPlug,
        # ou bien le mettre tout de suite après création (comme ci-dessous) :
        status_after = _safe_json_loads(settings.STATUS_AFTER_PAY_JSON, default={}) or {}
        next_status = status_after.get(acompte_num, f"Payé acompte {acompte_num}")
        set_status(item_id, settings.STATUS_COLUMN_ID, next_status)

        logger.info(f"[OK] item={item_id} acompte={acompte_num} amount_cents={amount_cents} url={payment_url}")
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


# ---------- PayPlug -> Webhook paiement réussi ----------
@app.post("/payplug/webhook")
async def payplug_webhook(request: Request):
    try:
        payload = await request.json()
        logger.info(f"[PP-WEBHOOK] payload={payload}")

        event_type = payload.get("type")
        data = payload.get("data") or {}
        payment = data.get("object") or data or {}
        metadata = _safe_json_loads(payment.get("metadata"), default={}) or {}
        if not metadata and "metadata" in payload:
            metadata = _safe_json_loads(payload.get("metadata"), default={}) or {}

        status = (payment.get("status") or "").lower()
        is_paid_flag = bool(payment.get("is_paid"))
        paid_like = event_type in {"payment.succeeded", "charge.succeeded", "payment_paid"} or \
                    status in {"paid", "succeeded"} or \
                    is_paid_flag
        if not paid_like:
            return JSONResponse({"ok": True, "ignored": True})

        item_id = metadata.get("item_id")
        acompte = metadata.get("acompte")
        if item_id and acompte in ("1", "2"):
            status_after = _safe_json_loads(settings.STATUS_AFTER_PAY_JSON, default={}) or {}
            next_status = status_after.get(acompte, f"Payé acompte {acompte}")
            try:
                set_status(int(item_id), settings.STATUS_COLUMN_ID, next_status)
                logger.info(f"[PP-WEBHOOK] set_status OK item_id={item_id} -> '{next_status}'")
            except Exception as e:
                logger.exception(f"[PP-WEBHOOK] set_status FAILED item_id={item_id}: {e}")
                return JSONResponse({"ok": False, "error": "monday_update_failed"}, status_code=200)

        return JSONResponse({"ok": True})

    except Exception as e:
        logger.exception(f"[PP-WEBHOOK] EXCEPTION {e}")
        return JSONResponse({"ok": False}, status_code=200)
