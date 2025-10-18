from fastapi import FastAPI, Request, HTTPException
import json
import re

from .config import settings
from .payments import _choose_api_key, cents_from_str, create_payment
from .monday import get_item_columns, set_link_in_column, set_status
from .evoliz import (
    create_quote,
    extract_public_link,
    extract_identifiers,
)

app = FastAPI(title="Energyz Payment Automation", version="2.3.0")


@app.get("/")
def root():
    return {"status": "ok", "message": "Energyz Payment Automation is live 🚀"}


# --------- helpers ---------
def _clean_number_text(s: str) -> str:
    """‘1 500,00 €’ → '1500.00' → utilisé avant cast float."""
    if not s:
        return "0"
    s = (
        s.replace("\u202f", "")
        .replace(" ", "")
        .replace("€", "")
        .strip()
        .replace(",", ".")
    )
    m = re.search(r"[-+]?\d*\.?\d+", s)
    return m.group(0) if m else "0"


def _to_float(s: str, default: float = 0.0) -> float:
    try:
        return float(_clean_number_text(s))
    except Exception:
        return default


# --------- webhook principal ---------
@app.post("/quote/from_monday")
async def quote_from_monday(request: Request):
    try:
        payload = await request.json()
        event = payload.get("event", {})
        item_id = event.get("pulseId") or event.get("itemId")
        column_id = event.get("columnId", "")

        if not item_id:
            raise HTTPException(status_code=400, detail="Item ID manquant.")

        # Détecteurs (acompte1/2 ou création devis)
        formula_columns = json.loads(settings.FORMULA_COLUMN_IDS_JSON)  # {"1":"...", "2":"..."}
        link_columns = json.loads(settings.LINK_COLUMN_IDS_JSON)        # {"1":"...", "2":"..."}
        status_after = json.loads(settings.STATUS_AFTER_PAY_JSON)       # {"1":"...","2":"..."}

        acompte_num = next((k for k, v in formula_columns.items() if v == column_id), None)
        is_create_quote = (column_id == settings.CREATE_QUOTE_STATUS_COLUMN_ID)

        if not acompte_num and not is_create_quote:
            raise HTTPException(status_code=400, detail=f"Colonne déclenchante inconnue: {column_id}")

        # Colonnes nécessaires (on veut aussi le __raw de l’adresse si monday.py l’expose)
        wanted = [
            settings.EMAIL_COLUMN_ID,
            settings.ADDRESS_COLUMN_ID,
            settings.DESCRIPTION_COLUMN_ID,
            settings.IBAN_FORMULA_COLUMN_ID,
            settings.QUOTE_AMOUNT_FORMULA_ID,  # total HT (fallback)
            settings.VAT_RATE_COLUMN_ID,       # TVA
            settings.TOTAL_HT_COLUMN_ID,
            settings.TOTAL_TTC_COLUMN_ID,
        ]
        cols = get_item_columns(item_id, wanted)

        # Adresse RAW (sera présente si monday.py ajoute id+"__raw" avec col.value)
        address_raw_json = cols.get(f"{settings.ADDRESS_COLUMN_ID}__raw")
        try:
            address_raw = json.loads(address_raw_json) if address_raw_json else None
        except Exception:
            address_raw = None

        # Valeurs usuelles
        name        = cols.get("name", "Client Energyz")
        email       = cols.get(settings.EMAIL_COLUMN_ID, "")
        address_txt = cols.get(settings.ADDRESS_COLUMN_ID, "")
        description = cols.get(settings.DESCRIPTION_COLUMN_ID, "")
        iban        = cols.get(settings.IBAN_FORMULA_COLUMN_ID, "")
        total_ht    = cols.get(settings.TOTAL_HT_COLUMN_ID) or cols.get(settings.QUOTE_AMOUNT_FORMULA_ID) or "0"
        vat_rate    = cols.get(settings.VAT_RATE_COLUMN_ID, "") or "20"

        # ======== ACOMPTES (PayPlug) ========
        if acompte_num:
            api_key = _choose_api_key(iban)
            amount_cents = cents_from_str(total_ht)
            if acompte_num == "2":
                amount_cents //= 2  # si tu veux 50% pour acompte 2 (sinon retire cette ligne)
            metadata = {"item_id": item_id, "acompte": acompte_num}

            payment_url = create_payment(api_key, amount_cents, email, address_txt, description, metadata)

            # Lien cliquable + statut
            set_link_in_column(item_id, link_columns[acompte_num], payment_url, f"Payer acompte {acompte_num}")
            set_status(item_id, settings.STATUS_COLUMN_ID, status_after[acompte_num])

            return {"status": "ok", "type": "acompte", "acompte": acompte_num, "payment_url": payment_url}

        # ======== DEVIS EVOLIZ ========
        unit_price_ht = _to_float(total_ht, 0.0)
        vr = _to_float(vat_rate, 20.0)
        label = name or description or "Devis"

        quote = create_quote(
            label=label,
            description=description,
            unit_price_ht=unit_price_ht,
            vat_rate=vr,
            recipient_name=name,
            recipient_email=email,
            recipient_address_json=address_raw,  # adresse structurée (street/town/postcode/iso2)
        )

        # Identifiants utiles + tentative de lien public
        qid, qnumber = extract_identifiers(quote)
        public_url = extract_public_link(quote)

        # Texte d’affichage pour Monday
        link_text = "Devis Evoliz"
        if qnumber:
            link_text += f" #{qnumber}"
        if qid:
            link_text += f" (ID:{qid})"

        # URL à poser : public si dispo, sinon app Evoliz (configurable)
        app_url = getattr(settings, "EVOLIZ_APP_BASE_URL", None) or settings.EVOLIZ_BASE_URL
        url_to_set = public_url or app_url

        # 👉 Pose un VRAI lien cliquable dans la colonne Devis
        set_link_in_column(item_id, settings.QUOTE_LINK_COLUMN_ID, url_to_set, link_text)

        return {
            "status": "ok",
            "type": "devis",
            "quote_id": qid,
            "quote_number": qnumber,
            "public_url": public_url,
            "link_used": url_to_set,
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Evoliz quote error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --------- endpoint test manuel pour PayPlug (optionnel) ---------
@app.post("/pay/acompte/{n}")
async def create_acompte_link(n: int):
    try:
        # IBAN par défaut de test : adapte si besoin
        api_key = _choose_api_key("FR76 1695 8000 0130 5670 5696 366")
        amount_cents = cents_from_str("1250.00") // (2 if n == 2 else 1)
        metadata = {"client": "Jean Dupont", "acompte": str(n)}
        url = create_payment(api_key, amount_cents, "jean@mail.com", "12 rue de Paris", "Installation solaire", metadata)
        return {"status": "ok", "acompte": n, "payment_url": url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
