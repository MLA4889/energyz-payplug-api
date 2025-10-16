import requests
import json
from .config import settings


def _choose_api_key(iban_display: str) -> str | None:
    if not iban_display:
        print("⚠️ Aucun IBAN trouvé dans Monday.")
        return None

    try:
        keys_json = (
            settings.PAYPLUG_KEYS_JSON
            if settings.PAYPLUG_MODE == "live"
            else settings.PAYPLUG_KEYS_TEST_JSON
        )
        iban_map = json.loads(keys_json)
        for iban_prefix, key in iban_map.items():
            if iban_prefix.replace(" ", "") in iban_display.replace(" ", ""):
                print(f"✅ Clé trouvée pour IBAN: {iban_prefix}")
                return key
        print("⚠️ IBAN non trouvé dans les clés PayPlug.")
        return None
    except Exception as e:
        print(f"❌ Erreur lecture JSON PayPlug : {e}")
        return None


def cents_from_str(amount_str: str) -> int:
    try:
        clean = str(amount_str).replace("€", "").replace(",", ".").strip()
        return int(round(float(clean) * 100))
    except Exception:
        print(f"⚠️ Montant invalide: {amount_str}")
        return 0


def create_payment(api_key: str, amount_cents: int, email: str, address: str, customer_name: str, metadata: dict):
    if not api_key:
        raise ValueError("❌ Clé PayPlug manquante.")
    if amount_cents <= 0:
        raise ValueError(f"❌ Montant invalide: {amount_cents}")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "amount": amount_cents,
        "currency": "EUR",
        "customer": {
            "email": email or "client@demo.com",
            "first_name": customer_name.split()[0] if customer_name else "",
            "last_name": customer_name.split()[-1] if len(customer_name.split()) > 1 else "",
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

    print(f"🔹 Envoi vers PayPlug : {json.dumps(payload, indent=2)}")

    res = requests.post("https://api.payplug.com/v1/payments", headers=headers, json=payload)
    if res.status_code >= 400:
        print(f"❌ Erreur PayPlug ({res.status_code}): {res.text}")
        res.raise_for_status()

    data = res.json()
    url = data.get("hosted_payment", {}).get("payment_url")
    if not url:
        raise Exception(f"Réponse PayPlug invalide: {data}")

    print(f"✅ Paiement OK: {url}")
    return url
