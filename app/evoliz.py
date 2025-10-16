import requests
from .config import settings

def get_access_token() -> str:
    payload = {"public_key": settings.EVOLIZ_PUBLIC_KEY, "secret_key": settings.EVOLIZ_SECRET_KEY}
    r = requests.post(f"{settings.EVOLIZ_BASE_URL}/api/login", json=payload, timeout=30)
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("Evoliz: pas de access_token reçu.")
    return token

def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

def create_client_if_needed(token: str, client_data: dict) -> int:
    r = requests.get(
        f"{settings.EVOLIZ_BASE_URL}/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/clients",
        headers=_auth(token),
        params={"search": client_data["name"]},
        timeout=30,
    )
    r.raise_for_status()
    hits = r.json().get("data", [])
    if hits:
        return hits[0]["clientid"]

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
        headers=_auth(token), json=payload, timeout=30
    )
    r.raise_for_status()
    return r.json()["clientid"]

def create_quote(token: str, client_id: int, quote_data: dict) -> dict:
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
        headers=_auth(token), json=payload, timeout=30
    )
    r.raise_for_status()
    return r.json()
