import requests
from .config import settings


def get_access_token():
    payload = {
        "public_key": settings.EVOLIZ_PUBLIC_KEY,
        "secret_key": settings.EVOLIZ_SECRET_KEY
    }

    # L'auth de l'API Evoliz passe par /v1/login (et non /api/login)
    url = f"{settings.EVOLIZ_BASE_URL}/v1/login"
    print(f"🔑 Auth vers Evoliz : {url}")
    r = requests.post(url, json=payload)
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise ValueError("Aucun token reçu depuis Evoliz")
    print("✅ Token Evoliz reçu avec succès")
    return token


def create_client_if_needed(token, client_data):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    search = client_data["name"]
    print(f"👤 Recherche du client '{search}' dans Evoliz...")

    # ✅ URL correcte
    url = f"{settings.EVOLIZ_BASE_URL}/v1/{settings.EVOLIZ_COMPANY_ID}/clients"
    print(f"GET {url}")

    r = requests.get(url, headers=headers, params={"search": search})
    r.raise_for_status()
    existing = r.json().get("data", [])

    if existing:
        print(f"✅ Client existant trouvé : {existing[0]['clientid']}")
        return existing[0]["clientid"]

    # Sinon, création du client
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

    print(f"🧾 Création d’un nouveau client : {payload}")
    r = requests.post(url, headers=headers, json=payload)
    r.raise_for_status()
    client = r.json()
    print("✅ Nouveau client créé :", client)
    return client.get("clientid")


def create_quote(token, client_id, quote_data):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    payload = {
        "clientid": client_id,
        "lines": [
            {
                "designation": quote_data["description"],
                "unit_price": quote_data["amount_ht"],
                "quantity": 1
            }
        ],
        "currency": "EUR"
    }

    # ✅ URL correcte
    url = f"{settings.EVOLIZ_BASE_URL}/v1/{settings.EVOLIZ_COMPANY_ID}/quotes"
    print(f"🧾 Création du devis sur {url}")
    r = requests.post(url, headers=headers, json=payload)
    r.raise_for_status()
    quote = r.json()
    print("✅ Devis créé :", quote)
    return quote
