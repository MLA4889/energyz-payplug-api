import requests
import json
from .config import settings


# --- Sélectionne la bonne clé PayPlug selon l’IBAN ---
def _choose_api_key(iban_display: str) -> str | None:
    """
    Sélectionne la clé PayPlug correspondant à l’IBAN trouvé dans Monday.
    """
    if not iban_display:
        print("⚠️ Aucun IBAN trouvé dans Monday.")
        return None

    try:
        # Sélectionne les clés live ou test selon PAYPLUG_MODE
        keys_json = (
            settings.PAYPLUG_KEYS_JSON
            if settings.PAYPLUG_MODE == "live"
            else settings.PAYPLUG_KEYS_TEST_JSON
        )

        iban_map = json.loads(keys_json)

        for iban_prefix, key in iban_map.items():
            if iban_prefix.replace(" ", "") in iban_display.replace(" ", ""):
                print(f"✅ Clé PayPlug trouvée pour IBAN: {iban_prefix}")
                return key

        print("⚠️ Aucun correspondance IBAN trouvée dans PAYPLUG_KEYS_JSON.")
        return None

    except Exception as e:
        print(f"❌ Erreur lecture clés PayPlug : {e}")
        return None


# --- Conversion euros → centimes ---
def cents_from_str(amount_str: str) -> int:
    """
    Convertit un montant en euros (ex: '1250.00') en centimes (int).
    """
    try:
        clean = str(amount_str).replace("€", "").replace(",", ".").strip()
        return int(round(float(clean) * 100))
    except Exception:
        print(f"⚠️ Impossible de convertir le montant: {amount_str}")
        return 0


# --- Crée un lien de paiement PayPlug ---
def create_payment(api_key: str, amount_cents: int, email: str, address: str, customer_name: str, metadata: dict):
    """
    Crée un lien de paiement PayPlug et retourne l’URL.
    """
    if not api_key:
        raise ValueError("❌ Clé API PayPlug manquante ou invalide.")
    if amount_cents <= 0:
        raise ValueError(f"❌ Montant invalide ({amount_cents}) pour PayPlug.")

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

    # --- Logs de debug clairs ---
    print("\n🔹===== Envoi d’un paiement PayPlug =====")
    print(f"🔹 amount_cents: {amount_cents}")
    print(f"🔹 email: {email}")
    print(f"🔹 client: {customer_name}")
    print(f"🔹 address: {address}")
    print(f"🔹 api_key prefix: {api_key[:10]}...")
    print("🔹 Payload JSON envoyé à PayPlug:\n", json.dumps(payload, indent=2))

    try:
        res = requests.post("https://api.payplug.com/v1/payments", headers=headers, json=payload)
        if res.status_code >= 400:
            print("❌ Erreur PayPlug:", res.text)
            res.raise_for_status()

        data = res.json()
        url = data.get("hosted_payment", {}).get("payment_url")
        if not url:
            raise Exception(f"Réponse PayPlug invalide: {data}")

        print(f"✅ Paiement créé avec succès: {url}\n")
        return url

    except requests.exceptions.RequestException as e:
        print(f"❌ Erreur requête HTTP PayPlug: {e}")
        raise

    except Exception as e:
        print(f"❌ Erreur interne PayPlug: {e}")
        raise
