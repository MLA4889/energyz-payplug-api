import requests
import json
from .config import settings


def _choose_api_key(iban_display: str) -> str | None:
    """
    Sélectionne la clé PayPlug correspondant à l'IBAN trouvé dans Monday.
    """
    if not iban_display:
        return None

    try:
        iban_map = json.loads(settings.PAYPLUG_KEYS_JSON if settings.PAYPLUG_MODE == "live" else settings.PAYPLUG_KEYS_TEST_JSON)
        for iban_prefix, key in iban_map.items():
            if iban_prefix.replace(" ", "") in iban_display.replace(" ", ""):
                return key
        return None
    except Exception as e:
        print(f"⚠️ Erreur lecture clés PayPlug : {e}")
        return None


def cents_from_str(amount_str: str) -> int:
    """
    Convertit un montant en euros (ex: '1250.00') en centimes (int).
    """
    try:
        clean = amount_str.replace("€", "").replace(",", ".").strip()
        return int(round(float(clean) * 100))
    except Exception:
        return 0


def create_payment(api_key: str, amount_cents: int, email: str, address: str, customer_name: str, metadata: dict):
    """
    Crée un lien de paiement PayPlug et retourne l’URL.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "amount": amount_cents,
        "currency": "EUR",
        "customer": {
            "email": email or "client@exemple.com",
            "first_name": customer_name.split()[0] if customer_name else "",
            "last_name": customer_name.split()[-1] if len(customer_name.split()) > 1 else "",
            "address1": address or "Adresse inconnue",
            "country": "FR"
        },
        "billing": {
            "email": email or "client@exemple.com",
            "address1": address or "Adresse inconnue",
            "country": "FR"
        },
        "hosted_payment": {
            "return_url": f"{settings.PUBLIC_BASE_URL}/success",
            "cancel_url": f"{settings.PUBLIC_BASE_URL}/cancel"
        },
        "notification_url": f"{settings.PUBLIC_BASE_URL}/pay/notify",
        "metadata": metadata
    }

    print("🔹 Payload PayPlug:", json.dumps(payload, indent=2))
    print("🔹 Using key:", api_key[:8] + "...")

    res = requests.post("https://api.payplug.com/v1/payments", headers=headers, json=payload)
    if res.status_code >= 400:
        print("❌ Erreur PayPlug:", res.text)
        res.raise_for_status()

    data = res.json()
    url = data.get("hosted_payment", {}).get("payment_url")
    if not url:
        raise Exception(f"Réponse PayPlug invalide: {data}")

    return url
