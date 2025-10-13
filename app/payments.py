import os
import requests
from .config import settings

# --- Configuration API PayPlug ---
PAYPLUG_API_URL = "https://api.payplug.com/v1/payments"


def _choose_api_key(iban_display_value: str) -> str | None:
    """
    Retourne la clé API PayPlug correspondant à l’IBAN détecté.
    Permet d’utiliser plusieurs comptes PayPlug selon le compte bancaire (IBAN).
    """
    if not iban_display_value:
        print("⚠️ Aucun IBAN détecté, retour à la clé par défaut (TEST).")
        return settings.PAYPLUG_API_KEYS.get("TEST")

    iban_clean = iban_display_value.replace(" ", "").upper()

    # --- Mapping IBAN → clé API ---
    mapping = {
        # IBAN Energyz MAR → Compte LIVE principal
        "FR761695800001005711982492": settings.PAYPLUG_API_KEYS.get("LIVE_ENERGYZ_MAR"),

        # IBAN Energyz FR → Compte TEST ou second compte
        "FR7616958000013056705696366": settings.PAYPLUG_API_KEYS.get("TEST_ENERGYZ_FR"),
    }

    for iban_prefix, key in mapping.items():
        if iban_clean.startswith(iban_prefix[:12]):  # match sur début IBAN
            print(f"✅ IBAN reconnu ({iban_display_value}) → utilisation clé correspondante.")
            return key

    print(f"⚠️ IBAN inconnu ({iban_display_value}) → fallback TEST.")
    return settings.PAYPLUG_API_KEYS.get("TEST")


def cents_from_str(amount_str: str) -> int:
    """
    Convertit '1000' ou '1 000,50 €' en centimes (int).
    """
    if not amount_str:
        return 0
    clean = (
        amount_str.replace("€", "")
        .replace(",", ".")
        .replace(" ", "")
        .strip()
    )
    try:
        return int(float(clean) * 100)
    except Exception:
        return 0


def create_payment(
    api_key: str,
    amount_cents: int,
    email: str = "",
    address: str = "",
    customer_name: str = "",
    metadata: dict = None,
) -> str:
    """
    Crée un paiement PayPlug et retourne l’URL du lien de paiement.
    """
    if not api_key:
        raise ValueError("❌ Clé API PayPlug manquante.")

    payload = {
        "amount": amount_cents,
        "currency": "EUR",
        "customer": {
            "email": email or "client@test.com",
            "first_name": customer_name or "Client",
            "address1": address or "Adresse inconnue",
        },
        "metadata": metadata or {},
        "hosted_payment": {"return_url": "https://www.energyz.fr"},
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    print(f"💳 Création du paiement PayPlug → montant={amount_cents} cts / client={customer_name}")

    r = requests.post(PAYPLUG_API_URL, json=payload, headers=headers)
    r.raise_for_status()
    data = r.json()

    url = data.get("hosted_payment", {}).get("payment_url")
    print(f"✅ Paiement créé → {url}")
    return url
