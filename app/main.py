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

app = FastAPI(title="Energyz PayPlug API", version="2.0 (metadata + payplug webhook)")


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


# -------------------- Health --------------------
@app.get("/")
def root():
    return {"status": "ok", "message": "Energyz PayPlug API (webhook-enabled) is live 🚀"}


# -------------------- Monday → Générer lien paiement --------------------
@app.post("/quote/from_monday")
async def quote_from_monday(request: Request):
    try:
        raw = await request.body()
        payload = _safe_json_loads(raw.decode("utf-8", errors="ignore"), default={}) or {}
        logger.info(f"[WEBHOOK] payload={payload}")

        # 1) Récupération infos de l'événement
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

        # 2) Lecture des colonnes utiles
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
        iban = cols.get(settings.IBAN_FORMULA_COLUMN_ID, "") or ""

        # 3) Calcul montant
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

        # 4) Trouver l'IBAN (formule ou fallback par Business Line)
        if not iban:
            iban_by_status = _safe_json_loads(getattr(settings, "IBAN_BY_STATUS_JSON", None), default={}) or {}
            business_status_label = cols.get(getattr(settings, "BUSINESS_STATUS_COLUMN_ID", "color_mkwnxf1h"), "")
            if business_status_label and business_status_label in iban_by_status:
                iban = iban_by_status[business_status_label]
        if not iban:
            raise HTTPException(
                status_code=400,
                detail="IBAN introuvable (formula vide + pas de fallback Business Line).",
            )

        # 5) Choisir la clé PayPlug selon l’IBAN/mode
        api_key = _choose_api_key(iban)
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail=f"Aucune clé PayPlug mappée pour IBAN '{iban}' (mode={settings.PAYPLUG_MODE}).",
            )

        # 6) Construire un metadata riche pour appariement côté webhook PayPlug
        metadata = {
            "board_id": str(getattr(settings, "MONDAY_BOARD_ID", "")),
            "item_id": str(item_id),
            "item_name": cols.get("name", ""),
            "acompte": acompte_num,  # "1" ou "2"
            "description": description or f"Acompte {acompte_num}",
            "source": "energyz-monday",
        }

        # 7) Créer le paiement PayPlug et stocker le lien dans Monday
        payment_url = create_payment(
            api_key=api_key,
            amount_cents=amount_cents,
            email=email,
            address=address,
            client_name=cols.get("name", "Client Energyz"),
            metadata=metadata,
        )

        set_link_in_column(item_id, link_columns[acompte_num], payment_url, f"Payer acompte {acompte_num}")

        # Statut post-création (optionnel : tu peux laisser le statut d’origine et ne changer qu’au webhook)
        status_after = _safe_json_loads(settings.STATUS_AFTER_PAY_JSON, default={}) or {}
        next_status = status_after.get(acompte_num, f"Payé acompte {acompte_num}")
        set_status(item_id, settings.STATUS_COLUMN_ID, next_status)

        logger.info(
            f"[OK] item={item_id} acompte={acompte_num} amount_cents={amount_cents} url={payment_url}"
        )
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


# -------------------- PayPlug → Webhook (paiement réussi) --------------------
@app.post("/payplug/webhook")
async def payplug_webhook(request: Request):
    """
    Webhook PayPlug :
    - Configure l'URL dans le dashboard PayPlug vers /payplug/webhook
    - À la réception d'un paiement réussi, on lit le metadata (item_id, acompte)
      et on met à jour le statut dans Monday.
    """
    try:
        payload = await request.json()
        logger.info(f"[PP-WEBHOOK] payload={payload}")

        # PayPlug envoie généralement {"type": "...", "data": {"object": {...}}}
        event_type = payload.get("type")
        data = payload.get("data") or {}
        payment = data.get("object") or data or {}
        metadata = _safe_json_loads(payment.get("metadata"), default={}) or {}

        # Robustesse : certains webhooks (ou tests) peuvent envoyer direct le paiement
        if not metadata and "metadata" in payload:
            metadata = _safe_json_loads(payload.get("metadata"), default={}) or {}

        # Détection "paiement réussi" (selon les variantes de schémas)
        status = (payment.get("status") or "").lower()
        is_paid_flag = bool(payment.get("is_paid"))
        paid_like = event_type in {"payment.succeeded", "charge.succeeded", "payment_paid"} or \
                    status in {"paid", "succeeded"} or \
                    is_paid_flag

        if not paid_like:
            # On accepte le webhook même si non paid (évite les retries en boucle)
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
                # On renvoie 200 quand même, sinon PayPlug retente en boucle;
                # si tu veux forcer un retry, renvoie 500 ici.
                return JSONResponse({"ok": False, "error": "monday_update_failed"}, status_code=200)

        return JSONResponse({"ok": True})

    except Exception as e:
        logger.exception(f"[PP-WEBHOOK] EXCEPTION {e}")
        # 200 pour éviter retentatives en boucle; mets 500 si tu veux que PayPlug retente
        return JSONResponse({"ok": False}, status_code=200)
