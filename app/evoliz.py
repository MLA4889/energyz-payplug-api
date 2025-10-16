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


def create_quote(token, client_id, quote_data: dict):
    vat_rate = float(quote_data.get("vat_rate", settings.DEFAULT_VAT_RATE))
    payload = {
        "clientid": client_id,
        "lines": [
            {
                "designation": quote_data["description"],
                "unit_price": quote_data["amount_ht"],
                "quantity": 1,
                "vat": vat_rate,
            }
        ],
        "currency": "EUR",
        "prices_include_vat": False
    }
    r = requests.post(
        f"{settings.EVOLIZ_BASE_URL}/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes",
        headers=_auth_headers(token),
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_invoice(token, client_id, invoice_data: dict):
    vat_rate = float(invoice_data.get("vat_rate", settings.DEFAULT_VAT_RATE))
    paytermid = int(invoice_data.get("paytermid", settings.EVOLIZ_PAYTERM_ID))
    documentdate = invoice_data.get("documentdate") or date.today().isoformat()
    payload = {
        "clientid": client_id,
        "documentdate": documentdate,
        "term": {"paytermid": paytermid},
        "lines": [
            {
                "designation": invoice_data["description"],
                "unit_price": invoice_data["amount_ht"],
                "quantity": 1,
                "vat": vat_rate,
            }
        ],
        "currency": "EUR",
        "prices_include_vat": False
    }
    r = requests.post(
        f"{settings.EVOLIZ_BASE_URL}/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/invoices",
        headers=_auth_headers(token),
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def fetch_pdf(token: str, doc_type: str, doc_id: int) -> tuple[bytes, str] | None:
    """
    Tente de récupérer le PDF (quote ou invoice).
    doc_type: "quotes" | "invoices"
    Retourne (content, filename) ou None si indisponible.
    """
    url = f"{settings.EVOLIZ_BASE_URL}/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/{doc_type}/{doc_id}/pdf"
    r = requests.get(url, headers=_auth_headers(token), timeout=60)
    if r.status_code != 200:
        return None
    fname = f"{doc_type[:-1]}_{doc_id}.pdf"
    return r.content, fname
