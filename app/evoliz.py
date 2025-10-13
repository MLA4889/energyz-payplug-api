import requests
from .config import settings


def get_access_token():
    """
    Authentifie avec les clés publiques/privées Evoliz et récupère un token d’accès.
    """
    payload = {
        "user_public_key": settings.EVOLIZ_PUBLIC_KEY,
        "user_secret_key": settings.EVOLIZ_SECRET_KEY
    }

    url = f"{settings.EVOLIZ_BASE_URL}/v1/login"
    print(f"🔑 [Evoliz] Auth vers {url}")
    print(f"📤 Payload envoyé : {payload}")

    try:
        r = requests.post(url, json=payload)
        print(f"📥 Réponse brute : {r.status_code} - {r.text}")
    except Exception as e:
        raise RuntimeError(f"Erreur réseau lors de la connexion à Evoliz : {e}")

    if r.status_code == 403:
        raise ValueError(
            "🚫 Accès refusé par Evoliz : tes clés API sont incorrectes "
            "ou ton application n’a pas les droits API activés. "
            "Vérifie dans Paramètres → Intégrations → API Evoliz."
        )

    if r.status_code != 200:
        raise RuntimeError(f"❌ Erreur d'authentification Evoliz ({r.status_code}) : {r.text}")

    try:
        token = r.json().get("access_token")
    except Exception:
        raise RuntimeError(f"Réponse JSON invalide depuis Evoliz : {r.text}")

    if not token:
        raise ValueError(f"❌ Token manquant dans la réponse Evoliz : {r.text}")

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
    print(f"📥 [Evoliz] Recherche client : {r.status_code} - {r.text}")

    if r.status_code == 401:
        raise ValueError("🔒 Token Evoliz expiré ou invalide. Essaie de régénérer un nouveau token.")

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
    print(f"📥 [Evoliz] Création client : {r.status_code} - {r.text}")
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
    print(f"📤 Payload : {payload}")

    r = requests.post(url, headers=headers, json=payload)
    print(f"📥 [Evoliz] Réponse création devis : {r.status_code} - {r.text}")

    if r.status_code == 401:
        raise ValueError("🔒 Token expiré ou invalide (401).")

    if r.status_code == 403:
        raise ValueError(
            "🚫 Accès interdit : ton compte Evoliz n’a pas les permissions pour créer un devis. "
            "Vérifie que le token correspond bien à une société avec accès API."
        )

    if r.status_code not in (200, 201):
        raise RuntimeError(f"❌ Erreur lors de la création du devis : {r.text}")

    print("✅ [Evoliz] Devis créé avec succès")
    return r.json()
