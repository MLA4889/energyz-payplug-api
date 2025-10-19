import json
import logging
import re
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from .config import settings
from .payments import _choose_api_key, cents_from_str, create_payment
from .monday import get_item_columns, set_link_in_column, set_status, compute_formula_value_for_item

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("energyz")

app = FastAPI(title="Energyz PayPlug API", version="2.1 stable")

def _clean_number_text(s: str) -> str:
    if not s:
        return "0"
    s = s.replace("\u202f", "").replace(" ", "").replace("€", "").strip()
    s = s.replace(",", ".")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    return m.group(0) if m else "0"

@app.post("/quote/from_monday")
async def quote_from_monday(request: Request):
    body = await request.json()
    event = body.get("event", {})
    pulse_id = event.get("pulseId")
    label = (event.get("value", {}).get("label", {}).get("text") or "").lower()

    if not pulse_id:
        raise HTTPException(status_code=400, detail="pulse_id manquant")

    acompte_num = 1 if "acompte 1" in label else 2 if "acompte 2" in label else 0
    if acompte_num == 0:
        raise HTTPException(status_code=400, detail="Label non reconnu pour acompte")

    columns = get_item_columns(pulse_id, [
        "lieu_mkkmwfws", "email_client", "montant_total__formula",
        "iban_formula", "color_mkwwwmdg"
    ])
    iban = columns.get("iban_formula") or ""
    montant_total = columns.get("montant_total__formula") or "0"
    email = columns.get("email_client") or ""
    client_name = columns.get("name") or ""

    amount_cents = cents_from_str(_clean_number_text(montant_total))
    if acompte_num == 1:
        amount_cents = int(amount_cents * 0.4)
    elif acompte_num == 2:
        amount_cents = int(amount_cents * 0.6)

    api_key = _choose_api_key(iban)
    pay_url = create_payment(api_key, amount_cents, email, None, client_name, {"item_id": pulse_id, "acompte": acompte_num})

    link_col_id = "link_mkww3qd4"
    set_link_in_column(pulse_id, link_col_id, pay_url, f"Payer acompte {acompte_num}")

    return JSONResponse({"ok": True, "url": pay_url, "amount_cents": amount_cents})
