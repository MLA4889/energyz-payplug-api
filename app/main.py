import json
import re
from fastapi import FastAPI, Request, HTTPException

from .config import settings
from .payments import _choose_api_key, cents_from_str, create_payment
from .monday import get_item_columns, set_link_in_column, set_status
from .evoliz import (
    create_quote,
    extract_identifiers,
    get_or_create_public_link,   # ← présent dans evoliz.py ci-dessus
    build_app_quote_url,
)

app = FastAPI(title="Energyz Payment Automation", version="2.6.1")


@app.get("/")
def root():
    return {"status": "ok", "message": "Energyz Payment Automation is live 🚀"}


# -------------- Helpers --------------

def _clean_number_text(s: str) -> str:
    if not s:
        return "0"
    s = s.replace("\u202f", "").replace(" ", "").replace("€", "").strip().replace(",", ".")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    return m.group(0) if m else "0"


def _to_float(s: str, default: float = 0.0) -> float:
    try:
        return float(_clean_number_text(s))
    except Exception:
        return default


def _best_description(cols: dict) -> str:
    """
    Retourne la description presta, même si la colonne est une Formula.
    Ordre:
      1) text (Formula si Monday la fournit)
      2) value RAW JSON (extrait "text"/"value" ou chaîne)
      3) fallback colonne texte (DESCRIPTION_FALLBACK_COLUMN_ID)
    """
    desc = cols.get(settings.DESCRIPTION_COLUMN_ID, "") or ""
    if desc:
        return desc.strip()

    raw = cols.get(f"{settings.DESCRIPTION_COLUMN_ID}__raw", "")
    if raw:
        try:
            j = json.loads(raw)
            if isinstance(j, str) and j.strip():
                return j.strip()
            if isinstance(j, dict):
                if isinstance(j.get("text"), str) and j["text"].strip():
                    return j["text"].strip()
                if isinstance(j.get("value"), str) and j["value"].strip():
                    return j["value"].strip()
        except Exception:
            if isinstance(raw, str) and raw.strip():
                return raw.strip()

    if settings.DESCRIPTION_FALLBACK_COLUMN_ID:
        fb = cols.get(settings.DESCRIPTION_FALLBACK_COLUMN_ID, "")
        if fb:
            return fb.strip()

    return ""


# -------------- Webhook --------------

@app.post("/quote/from_monday")
async def quote_from_monday(request: Request):
    try:
        payload = await request.json()
        event = payload.get("event", {})
        item_id = event.get("pulseId") or event.get("itemId")
        column_id = event.get("columnId", "")

        if not item_id:
            raise HTTPException(status_code=400, detail="Item ID manquant.")

        formula_columns = json.loads(settings.FORMULA_COLUMN_IDS_JSON)
        link_columns = json.loads(settings.LINK_COLUMN_IDS_JSON)
        status_after = json.loads(settings.STATUS_AFTER_PAY_JSON)

        acompte_num = next((k for k, v in formula_columns.items() if v == column_id), None)
        is_create_quote = column_id == settings.CREATE_QUOTE_STATUS_COLUMN_ID
        if not acompte_num and not is_create_quote:
            raise HTTPException(status_code=400, detail=f"Colonne déclenchante inconnue: {column_id}")

        wanted = [
            settings.EMAIL_COLUMN_ID,
            settings.ADDRESS_COLUMN_ID,
            settings.DESCRIPTION_COLUMN_ID,
            settings.IBAN_FORMULA_COLUMN_ID,
            settings.QUOTE_AMOUNT_FORMULA_ID,
            settings.VAT_RATE_COLUMN_ID,
            settings.TOTAL_HT_COLUMN_ID,
            settings.TOTAL_TTC_COLUMN_ID,
        ]
        if settings.DESCRIPTION_FALLBACK_COLUMN_ID:
            wanted.append(settings.DESCRIPTION_FALLBACK_COLUMN_ID)

        cols = get_item_columns(item_id, wanted)

        # Adresse RAW (structurée)
        address_raw_json = cols.get(f"{settings.ADDRESS_COLUMN_ID}__raw")
        try:
            address_raw = json.loads(address_raw_json) if address_raw_json else None
        except Exception:
            address_raw = None

        # Données
        name = cols.get("name", "Client Energyz")
        email = cols.get(settings.EMAIL_COLUMN_ID, "")
        address_txt = cols.get(settings.ADDRESS_COLUMN_ID, "")
        description = _best_description(cols)           # ← Désignation = Description presta
        iban = cols.get(settings.IBAN_FORMULA_COLUMN_ID, "")
        total_ht = cols.get(settings.TOTAL_HT_COLUMN_ID) or cols.get(settings.QUOTE_AMOUNT_FORMULA_ID) or "0"
        vat_rate = cols.get(settings.VAT_RATE_COLUMN_ID, "") or "20"

        # -------- Acomptes --------
        if acompte_num:
            api_key = _choose_api_key(iban)
            amount_cents = cents_from_str(total_ht)
            if acompte_num == "2":
                amount_cents //= 2
            metadata = {"item_id": item_id, "acompte": acompte_num}
            payment_url = create_payment(api_key, amount_cents, email, address_txt, description, metadata)
            set_link_in_column(item_id, link_columns[acompte_num], payment_url, f"Payer acompte {acompte_num}")
            set_status(item_id, settings.STATUS_COLUMN_ID, status_after[acompte_num])
            return {"status": "ok", "type": "acompte", "acompte": acompte_num, "payment_url": payment_url}

        # -------- Devis Evoliz --------
        unit_price_ht = _to_float(total_ht, 0.0)
        vr = _to_float(vat_rate, 20.0)
        label = name or description or "Devis"

        quote = create_quote(
            label=label,
            description=description,  # ← utilisé comme désignation Evoliz
            unit_price_ht=unit_price_ht,
            vat_rate=vr,
            recipient_name=name,
            recipient_email=email,
            recipient_address_json=address_raw,
        )

        qid, qnumber = extract_identifiers(quote)

        # Lien public (création/lecture automatique)
        public_url = get_or_create_public_link(qid, recipient_email=email)
        deep_link = build_app_quote_url(qid)

        link_text = "Devis Evoliz"
        if qnumber:
            link_text += f" #{qnumber}"
        if qid:
            link_text += f" (ID:{qid})"

        url_to_set = public_url or deep_link or settings.EVOLIZ_BASE_URL
        set_link_in_column(item_id, settings.QUOTE_LINK_COLUMN_ID, url_to_set, link_text)

        return {
            "status": "ok",
            "type": "devis",
            "quote_id": qid,
            "quote_number": qnumber,
            "public_url": public_url,
            "deep_link": deep_link,
            "link_used": url_to_set,
            "designation_used": description,
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Evoliz quote error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
