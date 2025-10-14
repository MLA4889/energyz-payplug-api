# app/evoliz.py
import requests
from datetime import date
from .config import settings


def get_access_token():
    payload = {
        "public_key": settings.EVOLIZ_PUBLIC_KEY,
        "secret_key": settings.EVOLIZ_SECRET_KEY
    }
    r = requests.post(f"{settings.EVOLIZ_BASE_URL}/api/login", json=payload, timeout=30)
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("Evoliz: pas de access_token reçu.")
    return token


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create_client_if_needed(token, client_data: dict):
    # Recherche par nom
    r = requests.get(
        f"{settings.EVOLIZ_BASE_URL}/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/clients",
        headers=_auth_headers(token),
        params={"search": client_data["name"]},
        timeout=30,
    )
    r.raise_for_status()
    existing = r.json().get("data", [])
    if existing:
        return existing[0]["clientid"]

    payload = {
        "name": client_data["name"],
        "type": "Professionnel" if client_data.get("client_type") == "Professionnel" else "Particulier",
        "address": {
            "addr": client_data.get("address", ""),
            "postcode": client_data.get("postcode", ""),
            "town": client_data.get("city", ""),
            "iso2": "FR",
        }
    }
    if client_data.get("client_type") == "Professionnel" and client_data.get("vat_number"):
        payload["vat_number"] = client_data["vat_number"]

    r = requests.post(
        f"{settings.EVOLIZ_BASE_URL}/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/clients",
        headers=_auth_headers(token),
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["clientid"]


# --------- payload builders ---------
def _payload_lines_base(description: str, amount_ht: float, vat_rate: float) -> dict:
    """Schéma moderne avec 'lines' et 'vat_rate' (prix envoyés HT)."""
    return {
        "lines": [
            {
                "designation": description,
                "unit_price": amount_ht,
                "quantity": 1,
                "vat_rate": float(vat_rate),
            }
        ],
        "currency": "EUR",
        "prices_include_vat": False,
    }


def _payload_items_legacy(description: str, amount_ht: float, vat_rate: float) -> dict:
    """Fallback quand l'API réclame items/documentdate/term.paytermid."""
    return {
        "documentdate": date.today().isoformat(),
        "term": {"paytermid": int(settings.EVOLIZ_PAYTERM_ID or 1)},
        "items": [
            {
                "designation": description,
                "unit_price": amount_ht,
                "quantity": 1,
                # certaines anciennes versions utilisent 'vat' au lieu de 'vat_rate'
                "vat_rate": float(vat_rate),
            }
        ],
        "currency": "EUR",
        "prices_include_vat": False,
    }


def _post_with_fallback(token: str, url: str, base: dict, description: str, amount_ht: float, vat_rate: float) -> dict:
    # 1) tentative 'lines'
    payload1 = {**base, **_payload_lines_base(description, amount_ht, vat_rate)}
    r1 = requests.post(url, headers=_auth_headers(token), json=payload1, timeout=30)
    if r1.status_code < 400:
        return r1.json()

    # 2) si erreur et message typique → repli 'items'
    try:
        err = r1.json()
    except Exception:
        err = {"raw": r1.text}
    msg = str(err).lower()
    needs_legacy = ("items" in msg) or ("documentdate" in msg) or ("term" in msg) or ("paytermid" in msg)

    if needs_legacy:
        payload2 = {**base, **_payload_items_legacy(description, amount_ht, vat_rate)}
        r2 = requests.post(url, headers=_auth_headers(token), json=payload2, timeout=30)
        if r2.status_code < 400:
            return r2.json()
        raise RuntimeError(f"Evoliz legacy error {r2.status_code}: {r2.text}")

    raise RuntimeError(f"Evoliz error {r1.status_code}: {r1.text}")


# --------- QUOTES / INVOICES ----------
def create_quote(token, client_id, quote_data: dict):
    """
    quote_data attend:
      - description (str)
      - amount_ht (float)
      - vat_rate (float)
    """
    description = quote_data["description"]
    amount_ht = float(quote_data["amount_ht"])
    vat_rate = float(quote_data.get("vat_rate", settings.DEFAULT_VAT_RATE))

    url = f"{settings.EVOLIZ_BASE_URL}/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes"
    base = {"clientid": client_id}
    return _post_with_fallback(token, url, base, description, amount_ht, vat_rate)


def create_invoice(token, client_id, invoice_data: dict):
    """
    invoice_data attend:
      - description (str)
      - amount_ht (float)
      - vat_rate (float)
      - paytermid (int) optionnel
      - documentdate (YYYY-MM-DD) optionnel
    """
    description = invoice_data["description"]
    amount_ht = float(invoice_data["amount_ht"])
    vat_rate = float(invoice_data.get("vat_rate", settings.DEFAULT_VAT_RATE))

    url = f"{settings.EVOLIZ_BASE_URL}/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/invoices"
    base = {
        "clientid": client_id,
        # on fournit malgré tout ces champs si l'API moderne les ignore, ça ne gêne pas
        "documentdate": invoice_data.get("documentdate", date.today().isoformat()),
        "term": {"paytermid": int(invoice_data.get("paytermid", settings.EVOLIZ_PAYTERM_ID or 1))},
    }
    return _post_with_fallback(token, url, base, description, amount_ht, vat_rate)
