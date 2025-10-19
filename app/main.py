import json
import logging
import os
import re
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from .config import settings
from .payments import _choose_api_key, cents_from_str, create_payment
from . import monday as m

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("energyz")

app = FastAPI(title="Energyz PayPlug API", version="2.6 (status-only-on-webhook)")


# -------------------- Utils --------------------
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


def _set_status_safe(item_id: int, column_id: str, label: str):
    """Pose un statut Monday sans faire échouer le flux si le libellé n'existe pas."""
    try:
        m.set_status(item_id, column_id, label)
    except Exception as e:
        msg = str(e)
        if "missingLabel" in msg or "This status label doesn't exist" in msg:
            logger.warning("[MONDAY] statut ignoré (label inexistant): '%s' (item_id=%s)", label, item_id)
        else:
            logger.exception("[MONDAY] set_status erreur non bloquante (item_id=%s, label=%s): %s", item_id, label, e)


# -------------------- Health/Ping --------------------
@app.get("/")
def root():
    return {"status": "ok", "service": "energyz-payplug-api", "version": app.version}


@app.get("/quote/from_monday")
def from_monday_ping():
    return {"ok": True}


# -------------------- Monday -> création du lien (NE CHANGE PAS LE STATUT) --------------------
@app.post("/quote/from_monday")
async def quote_from_monday(request: Request):
    try:
        raw = await request.body()
        payload = _safe_json_loads(raw.decode("utf-8", errors="ignore"), default={}) or {}
        logger.info(f"[WEBHOOK] payload={payload}")

        # 1) challenge d’enregistrement
        if isinstance(payload, dict) and "challenge" in payload:
            return JSONResponse(content={"challenge": payload["challenge"]})

        # 2) évènement normal
        event = payload.get("event") or {}
        item_id = event.get("pulseId") or event.get("itemId")
        if not item_id:
            raise HTTPException(status_code=400, detail="Item ID manquant (pulseId/itemId).")

        trigger_col = event.get("columnId")
        trigger_status_col = getattr(settings, "TRIGGER_STATUS_COLUMN_ID", "status")
        trigger_labels = _safe_json_loads(
            getattr(settings, "TRIGGER_LABELS_JSON", None),
            default={"1": "Générer acompte 1", "2": "Générer acompte 2"},
        ) or {"1": "Générer acompte 1", "2": "Générer acompte 2"}

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

        # Colonnes de travail
        formula_cols = _safe_json_loads(settings.FORMULA_COLUMN_IDS_JSON, default={}) or {}
        link_columns = _safe_json_loads(settings.LINK_COLUMN_IDS_JSON, default={}) or {}
        if acompte_num not in formula_cols or acompte_num not in link_columns:
            raise HTTPException(status_code=500, detail=f"FORMULA_COLUMN_IDS_JSON/LINK_COLUMN_IDS_JSON sans clé '{acompte_num}'.")

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
        logger.info(f"[MONDAY] item_id={item_id} values={cols}")

        email       = cols.get(settings.EMAIL_COLUMN_ID, "") or ""
        address     = cols.get(settings.ADDRESS_COLUMN_ID, "") or ""
        description = cols.get(settings.DESCRIPTION_COLUMN_ID, "") or ""
        item_name   = (cols.get("name", "") or "Client Energyz").strip()

        # ---------- MONTANT ----------
        formula_id  = formula_cols[acompte_num]
        acompte_txt = _clean_number_text(cols.get(formula_id, ""))

        if float(acompte_txt or "0") <= 0:
            computed = m.compute_formula_value_for_item(formula_id, int(item_id))
            if computed is not None and computed > 0:
                acompte_txt = str(computed)

        if float(acompte_txt or "0") <= 0:
            total_ht_txt = _clean_number_text(cols.get(settings.QUOTE_AMOUNT_FORMULA_ID, "0"))
            if float(total_ht_txt) > 0:
                acompte_txt = str(float(total_ht_txt) / 2.0)
            else:
                raise HTTPException(status_code=400, detail="Montant introuvable (formula + recalcul + total HT vides).")

        amount_cents = cents_from_str(acompte_txt)
        if amount_cents <= 0:
            raise HTTPException(status_code=400, detail=f"Montant invalide après parsing: '{acompte_txt}'.")

        # ---------- IBAN / KEY ----------
        forced_iban = (os.getenv("FORCED_IBAN") or getattr(settings, "FORCED_IBAN", "") or "").strip()
        forced_key  = (os.getenv("FORCED_PAYPLUG_KEY") or getattr(settings, "FORCED_PAYPLUG_KEY", "") or "").strip()

        if forced_iban:
            iban = forced_iban
        else:
            iban = (cols.get(settings.IBAN_FORMULA_COLUMN_ID, "") or "").strip()
            if not iban:
                iban_by_status = _safe_json_loads(getattr(settings, "IBAN_BY_STATUS_JSON", None), default={}) or {}
                business_col_id = getattr(settings, "BUSINESS_STATUS_COLUMN_ID", "color_mkwnxf1h")
                business_label  = (cols.get(business_col_id, "") or "").strip()
                if business_label and business_label in iban_by_status:
                    iban = iban_by_status[business_label]
            if not iban:
                raise HTTPException(status_code=400, detail="IBAN introuvable (ni FORCED_IBAN, ni formula, ni mapping Business Line).")

        if forced_key:
            api_key = forced_key
        else:
            api_key = _choose_api_key(iban)
            if not api_key:
                raise HTTPException(
                    status_code=400,
                    detail=f"Aucune clé PayPlug pour IBAN '{iban}'. "
                           f"Soit définis FORCED_PAYPLUG_KEY, soit poses PAYPLUG_* selon le mode.",
                )

        # ---------- Création paiement ----------
        desc = (description or f"{item_name} — Acompte {acompte_num}").strip()
        payment_url = create_payment(
            api_key=api_key,
            amount_cents=amount_cents,
            email=email,
            address=address,
            client_name=item_name,
            metadata={
                "item_id": str(item_id),
                "item_name": item_name,
                "acompte": acompte_num,
                "description": desc,
                "source": "energyz-monday",
            },
        )
        if not payment_url:
            raise HTTPException(status_code=500, detail="URL PayPlug manquante dans la réponse.")

        # 👉 On pose UNIQUEMENT le lien ; AUCUN changement de statut ici
        m.set_link_in_column(item_id, link_columns[acompte_num], payment_url, f"Payer acompte {acompte_num}")

        logger.info(f"[OK] item={item_id} acompte={acompte_num} amount_cents={amount_cents} url={payment_url}")
        return {"status": "ok", "item_id": item_id, "acompte": acompte_num, "amount_cents": amount_cents, "payment_url": payment_url}

    except HTTPException as e:
        logger.error(f"[HTTP] {e.status_code} {e.detail}")
        raise
    except Exception as e:
        logger.exception(f"[EXCEPTION] {e}")
        raise HTTPException(status_code=500, detail=f"Erreur webhook Monday : {e}")


# -------------------- PayPlug -> Webhook paiement réussi (POSE LE STATUT PAYÉ) --------------------
@app.post("/payplug/webhook")
async def payplug_webhook(request: Request):
    try:
        payload = await request.json()
        logger.info(f"[PP-WEBHOOK] payload={payload}")

        def _as_dict(x):
            if isinstance(x, dict):
                return x
            try:
                return json.loads(x) if isinstance(x, str) else {}
            except Exception:
                return {}

        event_type = payload.get("type") or payload.get("event") or ""
        data = payload.get("data") or {}
        obj  = data.get("object") or data or payload.get("object") or {}

        meta = obj.get("metadata")
        metadata = _as_dict(meta) if meta else _as_dict(payload.get("metadata"))

        status = (obj.get("status") or "").lower()
        is_paid_flag = bool(obj.get("is_paid") or obj.get("paid") or obj.get("paid_at"))
        paid_like = (
            event_type in {"payment.succeeded", "charge.succeeded", "payment_paid", "payment.success"} or
            status in {"paid", "succeeded", "succeeded_pending"} or
            is_paid_flag
        )
        if not paid_like:
            return JSONResponse({"ok": True, "ignored": True})

        item_id = metadata.get("item_id")
        acompte = metadata.get("acompte")
        if not item_id or acompte not in ("1", "2"):
            logger.error(f"[PP-WEBHOOK] metadata incomplète: item_id={item_id} acompte={acompte}")
            return JSONResponse({"ok": False, "error": "bad_metadata"}, status_code=200)

        # ➜ Pose “Payé acompte X”
        status_after = _safe_json_loads(getattr(settings, "STATUS_AFTER_PAY_JSON", None), default={}) or {}
        label = status_after.get(acompte, f"Payé acompte {acompte}")
        _set_status_safe(int(item_id), getattr(settings, "STATUS_COLUMN_ID", "status"), label)

        return JSONResponse({"ok": True})

    except Exception as e:
        logger.exception(f"[PP-WEBHOOK] EXCEPTION {e}")
        return JSONResponse({"ok": False}, status_code=200)


# -------------------- Fallback admin (test manuel) --------------------
@app.get("/payplug/mark_paid")
def mark_paid(item_id: int, acompte: str, token: str):
    """Marque payé via URL (pour test manuel) — protégé par ADMIN_HOOK_TOKEN."""
    admin_token = (os.getenv("ADMIN_HOOK_TOKEN") or "").strip()
    if not admin_token or token != admin_token:
        raise HTTPException(status_code=403, detail="Forbidden")

    if acompte not in ("1", "2"):
        raise HTTPException(status_code=400, detail="acompte doit être '1' ou '2'")

    status_after = _safe_json_loads(getattr(settings, "STATUS_AFTER_PAY_JSON", None), default={}) or {}
    label = status_after.get(acompte, f"Payé acompte {acompte}")
    _set_status_safe(int(item_id), getattr(settings, "STATUS_COLUMN_ID", "status"), label)
    return {"ok": True, "item_id": item_id, "acompte": acompte}
