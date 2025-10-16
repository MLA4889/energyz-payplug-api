import requests
from fastapi import HTTPException
from .config import settings
import json


# --- Convertir un montant en centimes ---
def cents_from_str(amount_str: str) -> int:
    try:
        amount = float(amount_str.replace("€", "").replace(",", ".").strip())
        return int(round(amount * 100))
    except Exception:
        return 0


# --- Choisir la clé API en fonction de l’IBAN et du mode ---
def _choose_api_key(iban_display: str) -> str:
    """
    Sélectionne la clé API PayPlug correspondant à l'IBAN affiché.
    """

    try:
        mode = getattr(settings, "PAYPLUG_MODE", "test").lower()
        if mode not in ["test", "live"]:
            mode = "test"

        if mode == "test":
            mapping = json.loads(settings.PAYPLUG_KEYS_TEST_JSON)
        else:
            mapping = json.loads(settings.PAYPLUG_KEYS_LIVE_JSON)
    except Exception as e:
        raise HTTPException(500, f"Erreur de configuration des clés PayPlug: {e}")

    for iban, key in mapping.items():
        if iban.replace(" ", "") in iban_display.replace(" ", ""):
            print(f"🔑 Clé PayPlug trouvée pour IBAN {iban} ({mode})")
            return key

    print("⚠️ Aucun IBAN correspondant trouvé pour PayPlug")
    return None


# --- Créer un paiement PayPlug ---
def create_payment(
    api_key: str,
    amount_cents: int,
    email: str,
    address: str,
    customer_name: str,
    metadata: dict,
):
    """
    Crée un paiement PayPlug et retourne l’URL du paiement hébergé.
    """

    if not api_key:
        raise HTTPException(400, "Aucune clé API PayPlug valide trouvée")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "amount": amount_cents,
        "currency": "EUR",
        "customer": {
            "email": email or "client@energyz.fr",
            "first_name": customer_name.split()[0] if customer_name else "Client",
            "last_name": customer_name.split()[-1] if len(customer_name.split()) > 1 else "",
            "address1": address or "Adresse non précisée",
            "country": "FR",
        },
        "hosted_payment": {
            "return_url": f"{settings.PUBLIC_BASE_URL}/success",
            "cancel_url": f"{settings.PUBLIC_BASE_URL}/cancel",
        },
        "metadata": metadata,
    }

    print(f"💳 Envoi à PayPlug ({amount_cents} centimes) pour {email} / {customer_name}")

    # Envoi vers API PayPlug
    url = "https://api.payplug.com/v1/payments"
    r = requests.post(url, headers=headers, json=payload)

    if r.status_code == 401:
        raise HTTPException(401, "Clé API PayPlug invalide ou non autorisée")
    elif r.status_code == 403:
        raise HTTPException(403, "Accès refusé à l’API PayPlug")
    elif r.status_code >= 400:
        raise HTTPException(r.status_code, f"Erreur PayPlug : {r.text}")

    data = r.json()
    print("✅ Paiement créé :", json.dumps(data, indent=2))

    try:
        return data["hosted_payment"]["payment_url"]
    except KeyError:
        raise HTTPException(500, f"Réponse inattendue de PayPlug : {data}")
