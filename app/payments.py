from typing import Optional
import payplug
from .config import settings


# ----------------------------------------------------------
# 🧩 ROUTAGE AUTOMATIQUE DES CLÉS PAYPLUG SELON L’IBAN
# ----------------------------------------------------------
def _choose_api_key(iban_display_value: str) -> Optional[str]:
    """
    Sélectionne la clé PayPlug (test ou live) en fonction de l'IBAN détecté.
    Retourne la clé API correspondante ou None si non trouvée.
    """
    if not iban_display_value:
        return None

    iban = iban_display_value.replace(" ", "").upper()

    # 🟩 LIVE : Compte 1
    if iban.startswith("FR7616958000013056705696366"):  # IBAN Energyz MAR
        print("✅ IBAN reconnu (Energyz MAR) → utilisation clé LIVE principale")
        return "sk_live_3Z0k3650qIaxaIB3V2Qdgd"

    # 🟦 TEST : Compte 2
    elif iban.startswith("FR7616958000010005711982492"):  # IBAN Energyz FR
        print("✅ IBAN reconnu (Energyz FR) → utilisation clé TEST")
        return "sk_test_3aV1MigpgyJDhuZ6hFn4yg"

    # 🟨 Si besoin, ajoute d'autres IBAN ici :
    # elif iban.startswith("FR76XXXXXXXXXXXX"):
    #     return "sk_live_XXXX..."

    # 🚫 IBAN inconnu
    print(f"⚠️ Aucun mapping trouvé pour IBAN : {iban_display_value}")
    return None


# ----------------------------------------------------------
# 💳 CRÉATION D’UN PAIEMENT PAYPLUG
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
    Crée un paiement PayPlug avec les infos du client et retourne l’URL du lien de paiement.
    """
    if not api_key:
        raise ValueError("API key PayPlug manquante pour ce paiement.")

    # Configuration de la clé PayPlug
    payplug.set_secret_key(api_key)

    # Création du paiement
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
# 💶 Conversion montant (string → cents)
# ----------------------------------------------------------
def cents_from_str(euro_str: str) -> int:
    """
    Convertit un montant en euros (string) en centimes (int).
    Exemple : "1 000,50" → 100050
    """
    if not euro_str:
        return 0
    euro_str = euro_str.replace(" ", "").replace(",", ".")
    try:
        return int(round(float(euro_str) * 100))
    except Exception:
        return 0
