import requests
import json
from .config import settings


def _choose_api_key(iban: str) -> str:
    """Sélectionne la clé PayPlug selon l’IBAN et le mode."""
    mode = settings.PAYPLUG_MODE.lower()
    key_dict = json.loads(settings.PAYPLUG_KEYS_TEST_JSON if mode == "test" else settings.PAYPLUG_KEYS_LIVE_JSON)
    return key_dict.get(iban)


def cents_from_str(amount_str: str) -> int:
    """Convertit '1250.00' → 125000 (en centimes)."""
    try:
        return int(round(float(amount_str) * 100))
    except Exception:
        return 0


def create_payment(api_key: str, amount_cents: int, email: str, address: str, client_name: str, metadata: dict):
    """Crée un lien de paiement PayPlug."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "amount": amount_cents,
        "currency": "EUR",
        "customer": {
            "email": email,
            "first_name": client_name.split(" ")[0],
            "last_name": client_name.split(" ")[-1],
            "address1": address
        },
        "metadata": metadata,
        "hosted_payment": {"return_url": settings.PUBLIC_BASE_URL}
    }

    url = "https://api.payplug.com/v1/payments"
    res = requests.post(url, headers=headers, json=payload)
    if res.status_code not in [200, 201]:
        raise Exception(f"Erreur PayPlug : {res.status_code} → {res.text}")

    data = res.json()
    return data.get("hosted_payment", {}).get("payment_url")
