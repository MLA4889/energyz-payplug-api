import requests
from .config import settings

def get_access_token():
    """
    Authentifie avec les clés publiques/privées Evoliz et récupère un token d’accès.
    """
    payload = {
        "public_key": settings.EVOLIZ_PUBLIC_KEY,
        "secret_key": settings.EVOLIZ_SECRET_KEY
    }

    url = f"{settings.EVOLIZ_BASE_URL}/v1/login"
    print(f"🔑 [Evoliz] Auth vers {url}")
    r = requests.post(url, json=payload)
    r.raise_for_status()
    token = r.json().get("access_token")

    if not token:
        raise ValueError("Token Evoliz manquant dans la réponse !")

    print("✅ [Evoliz] Token obtenu avec succès")
    return token


def create_client_if_needed(token: str, client_data: dict):
    """
    Recherche un client par nom, le crée s’il n’existe pas.
    """
    headers = {"Authorization": f"Bearer {token}"}
    search_name = client_data["name"]

    print(f"👤 [Evoliz] Recherche du client '{search_name}'")

    r = requests.get(
        f"{settings.EVOLIZ_BASE_URL}/v1/companies/{settings.EVOLIZ_COMPANY_ID}/clients",
        headers=headers,
        params={"search": search_name}
    )
    r.raise_for_status()
    data = r.json().get("data", [])
    if data:
        client_id = data[0]["clientid"]
        print(f"✅ [Evoliz] Client trouvé : ID {client_id}")
        return client_id

    print("🆕 [Evoliz] Création d’un nouveau client...")

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

    r = requests.post(
        f"{settings.EVOLIZ_BASE_URL}/v1/companies/{settings.EVOLIZ_COMPANY_ID}/clients",
        headers=headers,
        json=payload
    )
    r.raise_for_status()
    client_id = r.json().get("clientid")
    print(f"✅ [Evoliz] Nouveau client créé : ID {client_id}")
    return client_id


def create_quote(token: str, client_id: int, quote_data: dict):
    """
    Crée un devis Evoliz lié au client donné.
    """
    headers = {"Authorization": f"Bearer {token}"}
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

    url = f"{settings.EVOLIZ_BASE_URL}/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes"
    print(f"📄 [Evoliz] Création du devis via {url}")

    r = requests.post(url, headers=headers, json=payload)
    if r.status_code != 201:
        print(f"❌ [Evoliz] Erreur {r.status_code}: {r.text}")
        r.raise_for_status()

    print("✅ [Evoliz] Devis créé avec succès")
    return r.json()
