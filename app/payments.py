from typing import Optional
import payplug
import json
from .config import settings


# ----------------------------------------------------------
# 🧠 Sélection automatique de la clé PayPlug selon IBAN et mode
# ----------------------------------------------------------
def _choose_api_key(iban_display_value: str) -> Optional[str]:
    """
    Sélectionne la clé PayPlug (LIVE ou TEST) en fonction de l'IBAN et du mode.
    - Nettoie les espaces et majuscules.
    - Cherche uniquement dans le dictionnaire du mode actuel.
    """
    if not iban_display_value:
        print("⚠️ Aucun IBAN fourni.")
        return None

    iban_clean = iban_display_value.strip().replace(" ", "").upper()

    # Lecture sécurisée des variables Render
    try:
        live_dict = settings.PAYPLUG_KEYS_LIVE
        test_dict = settings.PAYPLUG_KEYS_TEST
    except Exception as e:
        print("🚨 Erreur de lecture des clés PayPlug:", e)
        return None

    # Affichage du mode actuel
    print(f"🧩 Mode PayPlug actif : {settings.PAYPLUG_MODE}")

    # --- Si on est en mode LIVE ---
    if settings.PAYPLUG_MODE.lower() == "live":
        for key, value in live_dict.items():
            if key.replace(" ", "").upper() == iban_clean:
                print(f"✅ IBAN reconnu (LIVE) : {iban_clean}")
                return value
        print(f"⚠️ IBAN non trouvé dans LIVE : {iban_clean}")

    # --- Si on est en mode TEST ---
    elif settings.PAYPLUG_MODE.lower() == "test":
        for key, value in test_dict.items():
            if key.replace(" ", "").upper() == iban_clean:
                print(f"✅ IBAN reconnu (TEST) : {iban_clean}")
                return value
        print(f"⚠️ IBAN non trouvé dans TEST : {iban_clean}")

    # --- Fallback : on regarde les deux (sécurité) ---
    for key, value in {**live_dict, **test_dict}.items():
        if key.replace(" ", "").upper() == iban_clean:
            print(f"✅ IBAN reconnu (Fallback) : {iban_clean}")
            return value

    print(f"🚫 Aucun mapping trouvé pour IBAN : {iban_clean}")
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
    Crée un paiement PayPlug et retourne le lien.
    """
    if not api_key:
        raise ValueError("❌ Clé API PayPlug absente, impossible de créer le paiement.")

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
    Convertit un montant en euros ('1 000,50') en centimes (100050).
    """
    if not euro_str:
        return 0
    euro_str = euro_str.replace(" ", "").replace(",", ".")
    try:
        return int(round(float(euro_str) * 100))
    except Exception:
        return 0
