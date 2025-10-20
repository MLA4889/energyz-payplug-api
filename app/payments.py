import requests
import json
from .config import settings

def _choose_api_key(iban: str) -> str:
    """Sélectionne la clé PayPlug selon l’IBAN et le mode (test/live)."""
    mode = (settings.PAYPLUG_MODE or "").lower()
    mapping_json = settings.PAYPLUG_KEYS_TEST_JSON if mode == "test" else settings.PAYPLUG_KEYS_LIVE_JSON
    key_dict = json.loads(mapping_json)
    return key_dict.get((iban or "").strip())

def cents_from_str(amount_str: str) -> int:
    """Convertit un montant texte en centimes (ex: '1250.00' → 125000)."""
    try:
        if not amount_str:
            return 0
        cleaned = str(amount_str).replace("€", "").replace("\u202f", "").replace(" ", "").replace(",", ".")
        return int(round(float(cleaned) * 100))
    except Exception:
        return 0

def create_payment(api_key: str, amount_cents: int, email: str, address: str, client_name: str, metadata: dict) -> str:
    """Crée un lien de paiement PayPlug + notifie notre webhook."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    public_base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    payload = {
        "amount": amount_cents,
        "currency": "EUR",
        "customer": {
            "email": email or "client@inconnu.fr",
            "first_name": (client_name or "Client").split(" ")[0],
            "last_name": (client_name or "Inconnu").split(" ")[-1],
            "address1": address or "Adresse non précisée"
        },
        "metadata": metadata,
        "hosted_payment": {
            "return_url": public_base or "https://energyz-company.monday.com/"
        },
        "notification_url": f"{public_base}/payplug/webhook",  # ← IMPORTANT : webhook PayPlug
        "description": metadata.get("description", "Paiement acompte Energyz")
    }
    url = "https://api.payplug.com/v1/payments"
    res = requests.post(url, headers=headers, json=payload, timeout=30)
    if res.status_code not in (200, 201):
        raise Exception(f"Erreur PayPlug : {res.status_code} → {res.text}")
    data = res.json()
    return data.get("hosted_payment", {}).get("payment_url")
