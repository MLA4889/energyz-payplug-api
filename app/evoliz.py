import requests
from .config import settings

__all__ = [
    "get_access_token",
    "create_client_if_needed",
    "create_quote",
]

def _base(url: str) -> str:
    base = (settings.EVOLIZ_BASE_URL or "").rstrip("/")
    return f"{base}{url}"

def _timeout() -> int:
    return int(getattr(settings, "EVOLIZ_TIMEOUT", 20))

def _raise_for_evoliz(r: requests.Response):
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    if r.status_code >= 400:
        msg = data.get("message") or data.get("error") or data
        raise RuntimeError(f"[Evoliz {r.status_code}] {msg}")

def get_access_token() -> str:
    """
    Auth Evoliz : POST /api/login avec public_key + secret_key -> access_token (Bearer)
    """
    payload = {
        "public_key": settings.EVOLIZ_PUBLIC_KEY,
        "secret_key": settings.EVOLIZ_SECRET_KEY,
    }
    r = requests.post(
        _base("/api/login"),
        json=payload,
        timeout=_timeout()
    )
    _raise_for_evoliz(r)
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("Login Evoliz OK mais 'access_token' absent. Vérifie clés & droits API.")
    return token

def create_client_if_needed(token: str, client_data: dict) -> int:
    """
    Crée le client si introuvable. Gère Particulier/Professionnel + TVA intracom.
    client_data attend : name, address, postcode, city, client_type, vat_number
    """
    headers = {"Authorization": f"Bearer {token}"}

    # 1) Recherche
    r = requests.get(
        _base(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/clients"),
        headers=headers,
        params={"search": client_data["name"]},
        timeout=_timeout()
    )
    _raise_for_evoliz(r)
    existing = (r.json() or {}).get("data", [])
    if existing:
        return existing[0]["clientid"]

    # 2) Création
    client_type = (client_data.get("client_type") or "Particulier")
    vat_number = client_data.get("vat_number")

    if client_type == "Professionnel" and not vat_number:
        raise RuntimeError("Client de type Professionnel : 'vat_number' (TVA intracom) est obligatoire.")

    payload = {
        "name": client_data["name"],
        "type": client_type,  # "Particulier" ou "Professionnel"
        "address": {
            "addr": client_data.get("address", "") or "",
            "postcode": client_data.get("postcode", "") or "",
            "town": client_data.get("city", "") or "",
            "iso2": "FR"
        }
    }
    if vat_number:
        payload["vat_number"] = vat_number

    r = requests.post(
        _base(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/clients"),
        headers=headers,
        json=payload,
        timeout=_timeout()
    )
    _raise_for_evoliz(r)
    client_id = (r.json() or {}).get("clientid")
    if not client_id:
        raise RuntimeError("Création client Evoliz : 'clientid' manquant dans la réponse.")
    return client_id

def create_quote(token: str, client_id: int, quote_data: dict) -> dict:
    """
    Crée un devis avec 1 ligne.
    Forçage de TVA 20% sur la ligne (comme demandé).
    """
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "clientid": client_id,
        "lines": [
            {
                "designation": quote_data["description"],
                "unit_price": quote_data["amount_ht"],
                "quantity": 1,
                "vat": 20.0  # force 20% dans tous les cas
            }
        ],
        "currency": "EUR"
    }
    r = requests.post(
        _base(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes"),
        headers=headers,
        json=payload,
        timeout=_timeout()
    )
    _raise_for_evoliz(r)
    return r.json()
