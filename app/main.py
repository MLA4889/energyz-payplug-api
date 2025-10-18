import json
import logging
import re
from fastapi import FastAPI, Request, HTTPException
from .config import settings
from .payments import _choose_api_key, cents_from_str, create_payment
from .monday import get_item_columns, set_link_in_column, set_status

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("energyz")

app = FastAPI(title="Energyz PayPlug API", version="1.3")

def _safe_json_loads(s, default=None):
    if s is None:
        return default
    if isinstance(s, dict):
        return s
    try:
        return json.loads(s)
    except Exception:
        return default

def _clean_amount_text(s: str) -> str:
    if not s:
        return "0"
    s = s.replace("\u202f", "").replace(" ", "").replace("€", "").strip()
    s = s.replace(",", ".")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    return m.group(0) if m else "0"

def _extract_status_label(value_json: dict) -> str:
    """
    Monday peut envoyer:
      {"label":{"index":1,"text":"Générer acompte 1"}, ...}
      ou {"label":"Acompte 1"} 
      ou {"value":"Acompte 1"}
    """
    if not isinstance(value_json, dict):
        return ""
    lbl = value_json.get("label")
    if isinstance(lbl, dict):
        return str(lbl.get("text") or "").strip()
    if isinstance(lbl, str):
        return lbl.strip()
    v = value_json.get("value")
    return str(v or "").strip()

@app.get("/")
def root():
    return {"status": "ok", "message": "Energyz PayPlug API is live 🚀"}

@app.post("/debug/echo")
async def debug_echo(request: Request):
    body = await request.body()
    try:
        j = json.loads(body.decode("utf-8") or "{}")
    except Exception:
        j = {"raw": body.decode("utf-8", errors="ignore")}
    logger.info(f"[DEBUG/ECHO] headers={dict(request.headers)} body={j}")
    return {"ok": True, "headers": dict(request.headers), "body": j}

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
            default={"1": "Acompte 1", "2": "Acompte 2"}
        ) or {"1": "Acompte 1", "2": "Acompte 2"}

        acompte_num = None
        if trigger_col == trigger_status_col:
            value_json = _safe_json_loads(event.get("value"), default={}) or {}
            current_label = _extract_status_label(value_json)
            lbl_norm = current_label.lower()
            # 1) match exact JSON config
            for k, label in trigger_labels.items():
                if lbl_norm == str(label).lower():
                    acompte_num = k
                    break
            # 2) sinon, heuristique: "acompte 1/2" dans le texte
            if acompte_num is None and "acompte" in lbl_norm:
                if "1" in lbl_norm:
                    acompte_num = "1"
                elif "2" in lbl_norm:
                    acompte_num = "2"

        if acompte_num not in ("1", "2"):
            raise HTTPException(
                status_code=400,
                detail=f"Label status non reconnu: columnId='{trigger_col}', attendu '{trigger_status_col}', label='{event.get('value')}'."
            )

        formula_cols = _safe_json_loads(settings.FORMULA_COLUMN_IDS_JSON, default={})
        link_columns = _safe_json_loads(settings.LINK_COLUMN_IDS_JSON, default={})
        if acompte_num not in formula_cols or acompte_num not in link_columns:
            raise HTTPException(status_code=500, detail=f"FORMULA/LINK JSON sans clé '{acompte_num}'.")

        needed_cols = [
            settings.EMAIL_COLUMN_ID,
            settings.ADDRESS_COLUMN_ID,
            settings.DESCRIPTION_COLUMN_ID,
            settings.IBAN_FORMULA_COLUMN_ID,
            settings.QUOTE_AMOUNT_FORMULA_ID,
            formula_cols[acompte_num],
            getattr(settings, "BUSINESS_STATUS_COLUMN_ID", "color_mkwnxf1h"),
        ]
        cols = get_item_columns(item_id, needed_cols)
        logger.info(f"[MONDAY] item_id={item_id} values={cols}")

        email = cols.get(settings.EMAIL_COLUMN_ID, "") or ""
        address = cols.get(settings.ADDRESS_COLUMN_ID, "") or ""
        description = cols.get(settings.DESCRIPTION_COLUMN_ID, "") or ""
        iban = cols.get(settings.IBAN_FORMULA_COLUMN_ID, "") or ""

        acompte_formula_val = cols.get(formula_cols[acompte_num], "")
        acompte_amount_txt = _clean_amount_text(acompte_formula_val)
        if float(acompte_amount_txt or "0") <= 0:
            total_ht_txt = _clean_amount_text(cols.get(settings.QUOTE_AMOUNT_FORMULA_ID, "0"))
            if float(total_ht_txt) > 0:
                acompte_amount_txt = str(float(total_ht_txt) / 2.0)
            else:
                raise HTTPException(status_code=400, detail="Montant introuvable (formula acompte et total HT vides).")

        amount_cents = cents_from_str(acompte_amount_txt)
        if amount_cents <= 0:
            raise HTTPException(status_code=400, detail=f"Montant invalide après parsing: '{acompte_amount_txt}'.")

        if not iban:
            iban_by_status = _safe_json_loads(getattr(settings, "IBAN_BY_STATUS_JSON", None), default={}) or {}
            business_status_label = cols.get(getattr(settings, "BUSINESS_STATUS_COLUMN_ID", "color_mkwnxf1h"), "")
            if business_status_label and business_status_label in iban_by_status:
                iban = iban_by_status[business_status_label]

        if not iban:
            raise HTTPException(status_code=400, detail="IBAN introuvable (formula vide + pas de fallback Business Line).")

        api_key = _choose_api_key(iban)
        if not api_key:
            raise HTTPException(status_code=400, detail=f"Aucune clé PayPlug mappée pour IBAN '{iban}' (mode={settings.PAYPLUG_MODE}).")

        metadata = {
            "item_id": str(item_id),
            "acompte": acompte_num,
            "description": description or f"Acompte {acompte_num}"
        }

        payment_url = create_payment(
            api_key=api_key,
            amount_cents=amount_cents,
            email=email,
            address=address,
            client_name=cols.get("name", "Client Energyz"),
            metadata=metadata
        )

        set_link_in_column(item_id, link_columns[acompte_num], payment_url, f"Payer acompte {acompte_num}")
        status_after = _safe_json_loads(settings.STATUS_AFTER_PAY_JSON, default={}) or {}
        next_status = status_after.get(acompte_num, f"Payé acompte {acompte_num}")
        set_status(item_id, settings.STATUS_COLUMN_ID, next_status)

        logger.info(f"[OK] item={item_id} acompte={acompte_num} amount_cents={amount_cents} url={payment_url}")
        return {"status": "ok", "item_id": item_id, "acompte": acompte_num, "amount_cents": amount_cents, "payment_url": payment_url}

    except HTTPException as e:
        logger.error(f"[HTTP] {e.status_code} {e.detail}")
        raise
    except Exception as e:
        logger.exception(f"[EXCEPTION] {e}")
        raise HTTPException(status_code=500, detail=f"Erreur webhook Monday : {e}")
