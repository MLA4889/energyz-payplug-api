import json
import requests
from .config import settings


def _choose_api_key(iban: str) -> str:
    data = json.loads(
        settings.PAYPLUG_KEYS_TEST_JSON if settings.PAYPLUG_MODE.lower() == "test" else settings.PAYPLUG_KEYS_LIVE_JSON
    )
    return data.get((iban or "").strip()) or list(data.values())[0]  # fallback sur la 1ère clé


def cents_from_str(amount: str) -> int:
    s = (amount or "").replace("€", "").replace("\u202f", "").replace(" ", "").replace(",", ".").strip()
    try:
        return int(round(float(s) * 100))
    except Exception:
        return 0


def create_payment(api_key: str, amount_cents: int, email: str, address: str, description: str, metadata: dict) -> str:
    url = "https://api.payplug.com/v1/payments"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "amount": amount_cents,
        "currency": "EUR",
        "customer": {"email": email, "address1": address},
        "metadata": metadata,
        "hosted_payment": {"return_url": "https://www.energyz.fr"},
        "description": description,
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    if not r.ok:
        raise Exception(f"Erreur PayPlug: {r.status_code} {r.text}")
    data = r.json()
    return data.get("hosted_payment", {}).get("payment_url")
