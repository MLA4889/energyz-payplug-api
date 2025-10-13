from fastapi import FastAPI, HTTPException, Body
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

# --- Health ----
@app.get("/")
def root():
    return {"status": "ok", "brand": settings.BRAND_NAME}

@app.get("/health")
def health():
    return {"status": "ok", "service": "energyz-payplug-api"}

# --- Debug (utile pour diagnostiquer) ---
@app.get("/debug/check/{item_id}/{n}")
def debug_check(item_id: int, n: int):
    formula_id = settings.FORMULA_COLUMN_IDS.get(str(n))
    link_col = settings.LINK_COLUMN_IDS.get(str(n))

    amount_display = get_formula_display_value(item_id, formula_id) if formula_id else ""
    iban_display = get_formula_display_value(item_id, settings.IBAN_FORMULA_COLUMN_ID) if settings.IBAN_FORMULA_COLUMN_ID else ""

    cols = get_item_columns(item_id, [c for c in [settings.EMAIL_COLUMN_ID, settings.ADDRESS_COLUMN_ID] if c])
    email = (cols.get(settings.EMAIL_COLUMN_ID, {}) or {}).get("text") or ""
    address = (cols.get(settings.ADDRESS_COLUMN_ID, {}) or {}).get("text") or ""

    api_key = _choose_api_key(iban_display)

    return {
        "item_id": item_id,
        "n": n,
        "formula_id_used": formula_id,
        "amount_display": amount_display,
        "iban_display": iban_display,
        "email": email,
        "address": address,
        "link_col_used": link_col,
        "api_key_found": bool(api_key),
    }

# --- Utils Monday payloads ---
def _parse_monday_webhook_body(body: dict[str, Any]) -> Tuple[int, str]:
    """Accepte payloads Monday: custom (pulseId) ou intégration (itemId)."""
    evt = body.get("event", {}) if isinstance(body, dict) else {}
    if "pulseId" in evt:
        try:
            return int(evt["pulseId"]), evt.get("pulseName", "")
        except Exception:
            pass
    if "itemId" in evt:
        try:
            return int(evt["itemId"]), ""
        except Exception:
            pass
    raise HTTPException(status_code=400, detail="Invalid Monday webhook body")

def _extract_status_label(body: dict[str, Any]) -> Optional[str]:
    """Récupère le label de statut si présent dans event.value."""
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
        return val.get("label")
    return None

def _challenge_response(body: dict[str, Any]) -> JSONResponse | None:
    if isinstance(body, dict) and "challenge" in body:
        return JSONResponse({"challenge": body["challenge"]})
    return None

# --- Endpoints métier ---
from fastapi import Request

@app.api_route("/pay/acompte/{n}", methods=["POST", "GET"])
async def create_acompte_link(n: int, request: Request):
    """
    Endpoint principal pour générer un lien PayPlug.
    Accepte POST (webhook réel) et GET (test Monday).
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    # ✅ Si Monday teste le webhook avec un "challenge"
    if "challenge" in body:
        return {"challenge": body["challenge"]}

    # ✅ Si Monday fait juste un test vide
    if not body:
        return {"status": "ok", "message": "Webhook test accepted by Monday"}

    # --- Reste de ton code inchangé ensuite ---
    from fastapi import HTTPException
    from .monday import get_item_columns, get_formula_display_value, set_link_in_column, set_status
    from .payments import create_payment, cents_from_str, _choose_api_key
    from .config import settings
    import json as _json

    expected_label = f"Générer acompte {n}"
    evt = body.get("event", {}) if isinstance(body, dict) else {}
    label = None
    try:
        val = evt.get("value")
        if isinstance(val, str):
            val = _json.loads(val)
        if isinstance(val, dict):
            label = val.get("label")
    except Exception:
        pass

    if label and label != expected_label:
        return {"status": "ignored", "reason": f"label={label} != {expected_label}"}

    item_id = int(evt.get("itemId", 0))
    if not item_id:
        raise HTTPException(400, "Missing itemId")

    column_ids = [settings.EMAIL_COLUMN_ID, settings.ADDRESS_COLUMN_ID]
    cols = get_item_columns(item_id, [c for c in column_ids if c])
    email = (cols.get(settings.EMAIL_COLUMN_ID, {}) or {}).get("text") or ""
    address = (cols.get(settings.ADDRESS_COLUMN_ID, {}) or {}).get("text") or ""

    formula_id = settings.FORMULA_COLUMN_IDS.get(str(n))
    if not formula_id:
        raise HTTPException(400, f"Formula column not configured for acompte {n}")
    amount_euros = get_formula_display_value(item_id, formula_id)
    amount_cents = cents_from_str(amount_euros)
    if amount_cents <= 0:
        raise HTTPException(400, f"Invalid amount for acompte {n}: '{amount_euros}'")

    iban_display_value = get_formula_display_value(item_id, settings.IBAN_FORMULA_COLUMN_ID)
    api_key = _choose_api_key(iban_display_value)
    if not api_key:
        raise HTTPException(400, f"Unknown IBAN key '{iban_display_value}' for PayPlug mapping")

    url = create_payment(
        api_key=api_key,
        amount_cents=amount_cents,
        email=email,
        address=address,
        customer_name="Client",
        metadata={"customer_id": item_id, "acompte": str(n)},
    )

    link_col = settings.LINK_COLUMN_IDS.get(str(n))
    if not link_col:
        raise HTTPException(400, f"Link column not configured for acompte {n}")
    set_link_in_column(item_id, settings.MONDAY_BOARD_ID, link_col, url, text="Payer")

    return {"status": "ok", "acompte": n, "payment_url": url}

    if res := _challenge_response(body):
        return res

    expected_label = f"Générer acompte {n}"
    label = _extract_status_label(body)
    if label and label != expected_label:
        return {"status": "ignored", "reason": f"label={label} != {expected_label}"}

    item_id, item_name = _parse_monday_webhook_body(body)

    column_ids = [cid for cid in [settings.EMAIL_COLUMN_ID, settings.ADDRESS_COLUMN_ID] if cid]
    cols = get_item_columns(item_id, column_ids) if column_ids else {}
    email = (cols.get(settings.EMAIL_COLUMN_ID, {}) or {}).get("text") or ""
    address = (cols.get(settings.ADDRESS_COLUMN_ID, {}) or {}).get("text") or ""

    formula_id = settings.FORMULA_COLUMN_IDS.get(str(n))
    if not formula_id:
        raise HTTPException(400, f"Formula column not configured for acompte {n}")
    amount_euros = get_formula_display_value(item_id, formula_id)
    amount_cents = cents_from_str(amount_euros)
    if amount_cents <= 0:
        raise HTTPException(400, f"Invalid amount for acompte {n}: '{amount_euros}'")

    if not settings.IBAN_FORMULA_COLUMN_ID:
        raise HTTPException(400, "IBAN_FORMULA_COLUMN_ID not configured")
    iban_display_value = get_formula_display_value(item_id, settings.IBAN_FORMULA_COLUMN_ID)
    api_key = _choose_api_key(iban_display_value)
    if not api_key:
        raise HTTPException(400, f"Unknown IBAN key '{iban_display_value}' for PayPlug mapping")

    url = create_payment(
        api_key=api_key,
        amount_cents=amount_cents,
        email=email,
        address=address,
        customer_name=item_name or "Client",
        metadata={"customer_id": item_id, "acompte": str(n)},
    )

    link_col = settings.LINK_COLUMN_IDS.get(str(n))
    if not link_col:
        raise HTTPException(400, f"Link column not configured for acompte {n}")
    set_link_in_column(item_id, settings.MONDAY_BOARD_ID, link_col, url, text="Payer")

    return {"status": "ok", "acompte": n, "payment_url": url}

@app.post("/pay/all")
async def create_all_links(body: dict = Body(...)):
    if res := _challenge_response(body):
        return res
    out: dict[str, Any] = {}
    for n in (1, 2, 3, 4):
        if str(n) in settings.LINK_COLUMN_IDS and str(n) in settings.FORMULA_COLUMN_IDS:
            try:
                out[str(n)] = await create_acompte_link(n, body)
            except HTTPException as e:
                out[str(n)] = {"status": "error", "detail": e.detail}
    return out

@app.post("/pay/notify")
async def payplug_notify(body: dict = Body(...)):
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

# --- Test direct pour Render → Monday ---
@app.get("/debug/test_write/{item_id}")
def debug_test_write(item_id: int):
    """
    Teste l'écriture d'un lien factice dans la colonne Lien Acompte 1 sur Monday.
    Utile pour valider que la mutation GraphQL fonctionne depuis Render.
    """
    try:
        link_col = settings.LINK_COLUMN_IDS.get("1")
        if not link_col:
            raise HTTPException(400, "Colonne de lien pour acompte 1 non configurée")

        test_url = "https://example.com/test"
        set_link_in_column(
            item_id=item_id,
            board_id=settings.MONDAY_BOARD_ID,
            column_id=link_col,
            url=test_url,
            text="Lien de test ✅",
        )
        return {
            "status": "ok",
            "message": f"Lien écrit dans {link_col}",
            "url": test_url,
            "item_id": item_id,
        }
    except Exception as e:
        raise HTTPException(500, detail=str(e))
