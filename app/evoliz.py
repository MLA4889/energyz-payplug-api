import requests
from .config import settings


def get_access_token():
    payload = {
        "public_key": settings.EVOLIZ_PUBLIC_KEY,
        "secret_key": settings.EVOLIZ_SECRET_KEY,
    }
    r = requests.post(f"{settings.EVOLIZ_BASE_URL}/api/login", json=payload)
    r.raise_for_status()
    token = r.json().get("access_token")
    print("🔑 Token récupéré depuis Evoliz ✅")
    return token


def create_client_if_needed(token, client_data):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    search = client_data["name"]
    print(f"👤 Vérification du client '{search}' dans Evoliz...")

    # 🔍 Recherche client existant
    r = requests.get(
        f"{settings.EVOLIZ_BASE_URL}/api/v1/{settings.EVOLIZ_COMPANY_ID}/clients",
        headers=headers,
        params={"search": search},
    )
    r.raise_for_status()
    existing = r.json().get("data", [])
    if existing:
        print("✅ Client déjà existant :", existing[0]["clientid"])
        return existing[0]["clientid"]

    # 🚀 Création d’un nouveau client
    payload = {
        "name": client_data["name"],
        "type": "Professionnel",
        "address": {
            "addr": client_data.get("address", ""),
            "postcode": client_data.get("postcode", ""),
            "town": client_data.get("city", ""),
            "iso2": "FR",
        },
    }
    print(f"🧾 Création d’un nouveau client dans Evoliz : {payload}")
    r = requests.post(
        f"{settings.EVOLIZ_BASE_URL}/api/v1/{settings.EVOLIZ_COMPANY_ID}/clients",
        headers=headers,
        json=payload,
    )
    r.raise_for_status()
    new_client = r.json()
    print("✅ Client créé avec succès :", new_client)
    return new_client.get("clientid")


def create_quote(token, client_id, quote_data):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {
        "clientid": client_id,
        "lines": [
            {
                "designation": quote_data["description"],
                "unit_price": quote_data["amount_ht"],
                "quantity": 1,
            }
        ],
        "currency": "EUR",
    }
    print("🧾 Création du devis :", payload)
    r = requests.post(
        f"{settings.EVOLIZ_BASE_URL}/api/v1/{settings.EVOLIZ_COMPANY_ID}/quotes",
        headers=headers,
        json=payload,
    )
    r.raise_for_status()
    quote = r.json()
    print("✅ Devis créé :", quote)
    return quote
