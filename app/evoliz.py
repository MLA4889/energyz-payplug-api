import requests
from .config import settings

def get_access_token():
    payload = {
        "public_key": settings.EVOLIZ_PUBLIC_KEY,
        "secret_key": settings.EVOLIZ_SECRET_KEY
    }
    r = requests.post(f"{settings.EVOLIZ_BASE_URL}/api/login", json=payload)
    r.raise_for_status()
    return r.json().get("access_token")

def create_client_if_needed(token, client_data):
    headers = {"Authorization": f"Bearer {token}"}
    search_url = f"{settings.EVOLIZ_BASE_URL}/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/clients"
    r = requests.get(search_url, headers=headers, params={"search": client_data["name"]})
    r.raise_for_status()
    existing = r.json().get("data", [])
    if existing:
        return existing[0]["clientid"]

    payload = {
        "name": client_data["name"],
        "type": "Professionnel",
        "address": {
            "addr": client_data.get("address", ""),
            "postcode": client_data.get("postcode", ""),
            "town": client_data.get("city", ""),
            "iso2": "FR"
        }
    }
    r = requests.post(search_url, headers=headers, json=payload)
    r.raise_for_status()
    return r.json()["clientid"]

def create_quote(token, client_id, quote_data):
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "clientid": client_id,
        "doctype": "quote",
        "rows": [
            {
                "designation": quote_data["description"],
                "quantity": 1,
                "unit_price": quote_data["amount_ht"]
            }
        ],
        "currency": "EUR"
    }
    url = f"{settings.EVOLIZ_BASE_URL}/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes"
    r = requests.post(url, headers=headers, json=payload)
    print("📤 Payload Evoliz:", payload)
    print("🌍 URL:", url)
    print("🔑 Token:", token[:10], "...")
    print("📦 Response:", r.text)
    r.raise_for_status()
    return r.json()
