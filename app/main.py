# app/main.py
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from typing import Any, Tuple, Optional
import json as _json

from .config import settings
from .monday import (
    get_item_columns,
    get_formula_display_value,
    set_link_in_column,
    set_status,
)
from .payments import create_payment, cents_from_str, _choose_api_key

app = FastAPI(title="ENERGYZ PayPlug API")


def _parse_monday_webhook_body(body: dict[str, Any]) -> Tuple[int, str]:
    """
    Supporte plusieurs formats de payload Monday :
    - Custom automation (body.custom)    : {"event":{"pulseId", "pulseName", ...}}
    - Intégration Webhooks (officielle)  : {"event":{"itemId", "boardId", "value": "..."}}
    - Bouton → webhook                    : {"event":{"itemId", ...}}

    Retourne: (item_id, item_name_ou_vide)
    """
    evt = body.get("event", {}) if isinstance(body, dict) else {}
    # Format custom : pulseId / pulseName
    if "pulseId" in evt:
        try:
            return int(evt["pulseId"]), evt.get("pulseName", "")
        except Exception:
            pass
    # Format intégration : itemId
    if "itemId" in evt:
        try:
            return int(evt["itemId"]), ""
        except Exception:
            pass
    raise HTTPException(status_code=400, detail="Invalid Monday webhook body")


def _extract_status_label(body: dict[str, Any]) -> Optional[str]:
    """
    Essaie d’extraire le label de statut quand il est présent (intégration Webhooks).
    event.value peut être soit un dict, soit une string JSON.
    Retourne le label (str) ou None si non disponible.
    """
    evt = body.get("event", {}) if isinstance(body, dict) else {}
    val = evt.get("value")
    if val is None:
        return None
    try:
        if isinstance(val, str):
            val = _json.loads(val)
    except Exception:
        return None
    if isinstance(val, dict):
        # Monday renvoie souvent {"label":"Générer acompte 1", "post_id":..., ...}
        return val.get("label")
    return None


def _challenge_response(body: dict[str, Any]) -> JSONResponse | None:
    # Validation des webhooks Monday (challenge)
    if isinstance(body, dict) and "challenge" in body:
        return JSONResponse({"challenge": body["challenge"]})
    return None


@app.get("/")
def root():
    return {"status": "ok", "brand": settings.BRAND_NAME}


@app.post("/pay/acompte/{n}")
async def create_acompte_link(n: int, request: Request):
    body = await request.json()
    if res := _challenge_response(body):
        return res

    # Si c’est un changement de statut, ne traiter que l’étiquette attendue
    expected_label = f"Générer acompte {n}"
    label = _extract_status_label(body)
    if label and label != expected_label:
        return {"status": "ignored", "reason": f"label={label} != {expected_label}"}

    # Récupération item_id & nom (si dispo)
    item_id, item_name = _parse_monday_webhook_body(body)

    # Lecture des colonnes email / adresse (tolère l’absence)
    column_ids = [cid for cid in [settings.EMAIL_COLUMN_ID, settings.ADDRESS_COLUMN_ID] if cid]
    cols = get_item_columns(item_id, column_ids) if column_ids else {}
    email = (cols.get(settings.EMAIL_COLUMN_ID, {}) or {}).get("text") or ""
    address = (cols.get(settings.ADDRESS_COLUMN_ID, {}) or {}).get("text") or ""

    # Colonne FORMULE du montant pour cet acompte
    formula_id = settings.FORMULA_COLUMN_IDS.get(str(n))
    if not formula_id:
        raise HTTPException(400, f"Formula column not configured for acompte {n}")
    amount_euros = get_formula_display_value(item_id, formula_id)  # affichage en €
    amount_cents = cents_from_str(amount_euros)
    if amount_cents <= 0:
        raise HTTPException(400, f"Invalid amount for acompte {n}: '{amount_euros}'")

    # Sélection de la clé PayPlug selon l'IBAN (FORMULE)
    if not settings.IBAN_FORMULA_COLUMN_ID:
        raise HTTPException(400, "IBAN_FORMULA_COLUMN_ID not configured")
    iban_display_value = get_formula_display_value(item_id, settings.IBAN_FORMULA_COLUMN_ID)
    api_key = _choose_api_key(iban_display_value)
    if not api_key:
        raise HTTPException(400, f"Unknown IBAN key '{iban_display_value}' for PayPlug mapping")

    # Création du paiement PayPlug
    url = create_payment(
        api_key=api_key,
        amount_cents=amount_cents,
        email=email,
        address=address,
        customer_name=item_name or "Client",  # fallback si on n’a pas pulseName
        metadata={"customer_id": item_id, "acompte": str(n)},
    )

    # Écriture du lien dans la colonne Link correspondante
    link_col = settings.LINK_COLUMN_IDS.get(str(n))
    if not link_col:
        raise HTTPException(400, f"Link column not configured for acompte {n}")
    set_link_in_column(item_id, settings.MONDAY_BOARD_ID, link_col, url, text="Payer")

    return {"status": "ok", "acompte": n, "payment_url": url}


@app.post("/pay/all")
async def create_all_links(request: Request):
    body = await request.json()
    if res := _challenge_response(body):
        return res

    out: dict[str, Any] = {}
    # On ignore le filtrage par label ici : on essaye de générer pour tous les acomptes configurés
    for n in (1, 2, 3, 4):
        if str(n) in settings.LINK_COLUMN_IDS and str(n) in settings.FORMULA_COLUMN_IDS:
            try:
                # On réutilise le corps d’origine sans modifier l’item id
                req = await create_acompte_link(n, request)
                out[str(n)] = req
            except HTTPException as e:
                out[str(n)] = {"status": "error", "detail": e.detail}
    return out


@app.post("/pay/notify")
async def payplug_notify(request: Request):
    """
    Callback PayPlug attendu (simplifié) :
    body: { "is_paid": true/false, "metadata": {"customer_id": <item_id>, "acompte": "1" } }
    """
    body = await request.json()
    if body.get("is_paid"):
        meta = body.get("metadata", {}) or {}
        try:
            item_id = int(meta.get("customer_id"))
        except Exception:
            return {"status": "ignored"}

        acompte = str(meta.get("acompte") or "")
        label = settings.STATUS_AFTER_PAY.get(acompte)
        if label:
            set_status(item_id, settings.MONDAY_BOARD_ID, settings.STATUS_COLUMN_ID, label)

    return {"status": "processed"}
