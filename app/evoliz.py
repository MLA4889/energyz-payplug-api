import requests
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
    # cherche par nom
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
    # pro intracom ?
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
    """
    quote_data attend:
      - description (str)
      - amount_ht (float)
      - vat_rate (float)  # ex: 20.0 ou 5.5
    """
    vat_rate = float(quote_data.get("vat_rate", settings.DEFAULT_VAT_RATE))

    payload = {
        "clientid": client_id,
        "lines": [
            {
                "designation": quote_data["description"],
                "unit_price": quote_data["amount_ht"],
                "quantity": 1,
                "vat": vat_rate,              # <--- TAUX DE TVA
            }
        ],
        "currency": "EUR",
        "prices_include_vat": False        # HT -> TVA ajoutée
    }
    r = requests.post(
        f"{settings.EVOLIZ_BASE_URL}/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes",
        headers=_auth_headers(token),
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
