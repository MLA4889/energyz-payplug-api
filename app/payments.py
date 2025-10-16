import requests
from .config import settings

def cents_from_str(amount_str: str):
    try:
        return int(float(amount_str.replace(",", ".").strip()) * 100)
    except Exception:
        return 0

def _choose_api_key(iban_display_value: str):
    """Choisit la clé API PayPlug selon l’IBAN (ou test/live par défaut)."""
    if "TEST" in (iban_display_value or "").upper():
        return settings.PAYPLUG_TEST_KEY
    return settings.PAYPLUG_LIVE_KEY

def create_payment(api_key: str, amount_cents: int, email: str, address: str, customer_name: str, metadata: dict):
    """Crée un paiement PayPlug."""
    headers = {"Authorization": f"Bearer {api_key}"}
    data = {
        "amount": amount_cents,
        "currency": "EUR",
        "customer": {
            "email": email,
            "first_name": customer_name.split()[0],
            "last_name": customer_name.split()[-1] if " " in customer_name else customer_name,
            "address1": address,
        },
        "metadata": metadata,
        "allow_save_card": False,
        "save_card": False,
    }
    r = requests.post("https://api.payplug.com/v1/payments", json=data, headers=headers)
    r.raise_for_status()
    return r.json().get("hosted_payment", {}).get("payment_url", "https://payplug.com/error")
