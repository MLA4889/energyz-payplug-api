from typing import Optional
import payplug
from .config import settings


# ----------------------------------------------------------
# 🧩 Sélection automatique de la clé PayPlug selon l’IBAN
# ----------------------------------------------------------
def _choose_api_key(iban_display_value: str) -> Optional[str]:
    """
    Sélectionne la clé PayPlug (live ou test) en fonction de l’IBAN
    à partir des variables Render PAYPLUG_KEYS_LIVE_JSON et PAYPLUG_KEYS_TEST_JSON.
    """
    if not iban_display_value:
        print("⚠️ Aucun IBAN fourni.")
        return None

    iban = iban_display_value.strip().replace(" ", "").upper()

    # 🔍 Recherche dans les clés LIVE
    live_keys = settings.PAYPLUG_KEYS_LIVE
    for k, v in live_keys.items():
        if k.replace(" ", "").upper() == iban:
            print(f"✅ IBAN reconnu dans LIVE : {iban}")
            return v

    # 🔍 Recherche dans les clés TEST
    test_keys = settings.PAYPLUG_KEYS_TEST
    for k, v in test_keys.items():
        if k.replace(" ", "").upper() == iban:
            print(f"✅ IBAN reconnu dans TEST : {iban}")
            return v

    print(f"🚫 Aucun mapping trouvé pour IBAN : {iban_display_value}")
    return None


# ----------------------------------------------------------
# 💳 Création d’un paiement PayPlug
# ----------------------------------------------------------
def create_payment(
    api_key: str,
    amount_cents: int,
    email: str,
    address: str,
    customer_name: str,
    metadata: dict,
) -> str:
    """
    Crée un paiement PayPlug et retourne le lien de paiement.
    """
    if not api_key:
        raise ValueError("Aucune clé PayPlug valide fournie pour ce paiement.")

    payplug.set_secret_key(api_key)

    payment = payplug.Payment.create(
        amount=amount_cents,
        currency="EUR",
        save_card=False,
        customer={
            "email": email or "client@inconnu.fr",
            "address1": address or "",
            "first_name": customer_name or "Client",
            "last_name": customer_name or "",
        },
        hosted_payment={
            "sent_by": "OTHER",
            "return_url": "https://monday.com",
            "cancel_url": "https://monday.com",
        },
        notification_url=f"{settings.PUBLIC_BASE_URL}/pay/notify",
        metadata=metadata,
    )

    print(f"💰 Paiement créé pour {customer_name} → {payment.hosted_payment.payment_url}")
    return payment.hosted_payment.payment_url


# ----------------------------------------------------------
# 💶 Conversion d’euros → centimes
# ----------------------------------------------------------
def cents_from_str(euro_str: str) -> int:
    """
    Convertit une chaîne d’euros ('1 000,50') en centimes (100050).
    """
    if not euro_str:
        return 0
    euro_str = euro_str.replace(" ", "").replace(",", ".")
    try:
        return int(round(float(euro_str) * 100))
    except Exception:
        return 0
