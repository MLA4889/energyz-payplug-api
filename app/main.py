import json
import logging
import re
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from .config import settings
from .payments import _choose_api_key, cents_from_str, create_payment
from . import monday as m

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("energyz")

app = FastAPI(title="Energyz PayPlug API", version="2.4 (diag + robust BL mapping)")

# --- MAPPING IBAN PAR DEFAUT (sécurité si ENV manquant / mal renseigné) ---
DEFAULT_IBAN_BY_STATUS = {
    # clés telles qu’affichées dans ta colonne “Business Line”
    "Energyz MAR":    "FR76 1695 8000 0130 5670 5696 366",
    "Energyz Divers": "FR76 1695 8000 0100 0571 1982 492",
}

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

def _normalize(s: str) -> str:
    return (s or "").strip().lower()

# -------------------- Health/Ping --------------------
@app.get("/")
def root():
    return {"status": "ok", "service": "energyz-payplug-api", "version": app.version}

@app.get("/quote/from_monday")
def from_monday_ping():
    return {"ok": True}

# -------------------- Endpoint DIAG (très utile) --------------------
@app.get("/diag/{item_id}")
def diag_item(item_id: int):
    needed = [
        settings.EMAIL_COLUMN_ID,
        settings.ADDRESS_COLUMN_ID,
        settings.DESCRIPTION_COLUMN_ID,
        settings.IBAN_FORMULA_COLUMN_ID,
        settings.QUOTE_AMOUNT_FORMULA_ID,
        getattr(settings, "BUSINESS_STATUS_COLUMN_ID", "color_mkwnxf1h"),
        "name",
    ]
    cols = m.get_item_columns(item_id, needed)

    # 1) IBAN calculé via la formule (même si text/value sont vides)
    iban_formula_calc = None
    try:
        iban_formula_calc = m.compute_formula_text_for_item(settings.IBAN_FORMULA_COLUMN_ID, int(item_id))
    except Exception as e:
        iban_formula_calc = f"ERROR: {e}"

    # 2) Fallback Business Line → IBAN (carte réellement utilisée)
    def _normalize(s: str) -> str: return (s or "").strip().lower()

    from .config import settings as s
    # ton mapping ENV
    env_map = _safe_json_loads(getattr(s, "IBAN_BY_STATUS_JSON", None), default={}) or {}
    # mapping défaut pour Energyz (si ENV vide ou incomplet)
    default_map = {
        "Energyz MAR":    "FR76 1695 8000 0130 5670 5696 366",
        "Energyz Divers": "FR76 1695 8000 0100 0571 1982 492",
    }
    merged_map = {**default_map, **env_map}

    bl_col = getattr(s, "BUSINESS_STATUS_COLUMN_ID", "color_mkwnxf1h")
    bl_value = (cols.get(bl_col, "") or "").strip()
    chosen_iban_from_bl = ""
    tried_keys = []
    if bl_value:
        bn = _normalize(bl_value)
        for k, v in merged_map.items():
            if not v:
                continue
            kn = _normalize(k)
            tried_keys.append(k)
            if bn == kn or bn.startswith(kn) or kn in bn:
                chosen_iban_from_bl = v.strip()
                break

    return {
        "item_id": item_id,
        "read": cols,                           # ce que renvoie l'API brute
        "iban_formula_calc": iban_formula_calc, # IBAN calculé via expression formula
        "business_line_value": bl_value,
        "bl_mapping_keys": list(merged_map.keys()),
        "bl_chosen_iban": chosen_iban_from_bl
    }


# -------------------- Webhook --------------------
@app.post("/quote/from_monday")
async def quote_from_monday(request: Request):
    try:
        body = await request.body()
        payload = _safe_json_loads(body.decode("utf-8", errors="ignore"), default={}) or {}
        logger.info(f"[WEBHOOK] payload={payload}")

        # 1) challenge d’enregistrement
        if isinstance(payload, dict) and "challenge" in payload:
            logger.info("[WEBHOOK] responding to challenge")
            return JSONResponse(content={"challenge": payload["challenge"]})

        # 2) appel normal
        event = payload.get("event") or {}
        item_id = event.get("pulseId") or event.get("itemId")
        if not item_id:
            raise HTTPException(status_code=400, detail="Item ID manquant (pulseId/itemId).")

        trigger_col = event.get("columnId")
        trigger_status_col = getattr(settings, "TRIGGER_STATUS_COLUMN_ID", "status")
        trigger_labels = _safe_json_loads(getattr(settings, "TRIGGER_LABELS_JSON", None),
                                          default={"1": "Générer acompte 1", "2": "Générer acompte 2"}) \
                          or {"1": "Générer acompte 1", "2": "Générer acompte 2"}

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
        iban        = (cols.get(settings.IBAN_FORMULA_COLUMN_ID, "") or "").strip()

        # IBAN via FORMULE (texte)
        if not iban:
            try:
                iban = (m.compute_formula_text_for_item(settings.IBAN_FORMULA_COLUMN_ID, int(item_id)) or "").strip()
                if iban:
                    logger.info(f"[IBAN] via formula API = '{iban}'")
            except Exception as e:
                logger.warning(f"[IBAN] compute_formula_text_for_item a échoué: {e}")

        # Montant acompte
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

        # ------- Fallback IBAN via Business Line (STATUT) -------
        business_col_id = getattr(settings, "BUSINESS_STATUS_COLUMN_ID", "color_mkwnxf1h")
        business_label  = (cols.get(business_col_id, "") or "").strip()
        logger.info(f"[IBAN] business_label='{business_label}'")

        # ENV puis défaut codé en dur
        env_map = _safe_json_loads(getattr(settings, "IBAN_BY_STATUS_JSON", None), default={}) or {}
        if not env_map:
            env_map = {}

        # Merge avec default (ENV prioritaire)
        merged_map = {**DEFAULT_IBAN_BY_STATUS, **env_map}

        if not iban and business_label:
            # matching robuste : exact / normalize / contains
            bl_norm = _normalize(business_label)
            keys_tried = []
            for k, v in merged_map.items():
                if not v:
                    continue
                kn = _normalize(k)
                keys_tried.append(k)
                if bl_norm == kn or bl_norm.startswith(kn) or kn in bl_norm:
                    iban = v.strip()
                    break
            logger.info(f"[IBAN] keys tried: {keys_tried}")

        if not iban:
            raise HTTPException(status_code=400, detail="IBAN introuvable (formule vide + pas de fallback Business Line).")

        # Clé PayPlug
        api_key = _choose_api_key(iban)
        if not api_key:
            raise HTTPException(status_code=400, detail=f"Aucune clé PayPlug mappée pour IBAN '{iban}' (mode={settings.PAYPLUG_MODE}).")

        client_name = cols.get("name", "Client Energyz")
        metadata = {"item_id": str(item_id), "acompte": acompte_num, "description": description or f"Acompte {acompte_num}"}

        payment_url = create_payment(
            api_key=api_key,
            amount_cents=amount_cents,
            email=email,
            address=address,
            client_name=client_name,
            metadata=metadata,
        )

        m.set_link_in_column(item_id, link_columns[acompte_num], payment_url, f"Payer acompte {acompte_num}")
        status_after = _safe_json_loads(settings.STATUS_AFTER_PAY_JSON, default={}) or {}
        next_status = status_after.get(acompte_num, f"Payé acompte {acompte_num}")
        m.set_status(item_id, settings.STATUS_COLUMN_ID, next_status)

        logger.info(f"[OK] item={item_id} acompte={acompte_num} amount_cents={amount_cents} url={payment_url}")
        return {"status": "ok", "item_id": item_id, "acompte": acompte_num, "amount_cents": amount_cents, "payment_url": payment_url}

    except HTTPException as e:
        logger.error(f"[HTTP] {e.status_code} {e.detail}")
        raise
    except Exception as e:
        logger.exception(f"[EXCEPTION] {e}")
        raise HTTPException(status_code=500, detail=f"Erreur webhook Monday : {e}")
