from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from typing import Any
from .config import settings
from .monday import (
    get_item_columns,
    get_formula_display_value,
    set_link_in_column,
    set_status,
)
from .payments import create_payment, cents_from_str, _choose_api_key

app = FastAPI(title="ENERGYZ PayPlug API")

def _parse_monday_webhook_body(body: dict[str, Any]) -> tuple[int, str]:
    try:
        item_id = int(body["event"]["pulseId"])
        item_name = body["event"]["pulseName"]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Monday webhook body")
    return item_id, item_name

def _challenge_response(body: dict[str, Any]) -> JSONResponse | None:
    if "challenge" in body:
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

    item_id, item_name = _parse_monday_webhook_body(body)

    cols = get_item_columns(item_id, [settings.EMAIL_COLUMN_ID, settings.ADDRESS_COLUMN_ID])
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
        customer_name=item_name,
        metadata={"customer_id": item_id, "acompte": str(n)},
    )

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

    out = {}
    for n in (1, 2, 3, 4):
        if str(n) in settings.LINK_COLUMN_IDS and str(n) in settings.FORMULA_COLUMN_IDS:
            try:
                req = await create_acompte_link(n, request)
                out[str(n)] = req
            except HTTPException as e:
                out[str(n)] = {"status": "error", "detail": e.detail}
    return out

@app.post("/pay/notify")
async def payplug_notify(request: Request):
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
