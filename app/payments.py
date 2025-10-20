from typing import Optional
import payplug
import logging

from .config import settings

logger = logging.getLogger("energyz")


# ---------- Utilitaires ----------
def _choose_api_key(iban_display_value: str) -> Optional[str]:
    """
    Choisit la clé PayPlug (test/live) selon l'IBAN détecté.
    """
    iban = (iban_display_value or "").replace(" ", "").upper()
    if settings.PAYPLUG_MODE == "test":
        return settings.PAYPLUG_TEST_KEY
    if "13056705696366" in iban:
        return settings.PAYPLUG_LIVE_KEY  # Energyz MAR
    if "10005711982492" in iban:
        return settings.PAYPLUG_LIVE_KEY  # Energyz Divers
    # par défaut
    return settings.PAYPLUG_LIVE_KEY


def cents_from_str(amount_str: str) -> int:
    """
    Convertit une chaîne en centimes.
    """
    try:
        amount = float(str(amount_str).replace(",", ".").strip())
        return int(round(amount * 100))
    except Exception:
        return 0


# ---------- Création du paiement ----------
def create_payment(
    api_key: str,
    amount_cents: int,
    email: str,
    address: str,
    client_name: str,
    metadata: dict,
) -> str:
    """
    Crée un paiement PayPlug hébergé et renvoie l'URL de paiement.
    """
    payplug.set_secret_key(api_key)

    # ----------- CONFIG DE REDIRECTION -----------
    return_url = "https://www.energyz.fr"   # <- après paiement validé
    cancel_url = "https://www.energyz.fr"   # <- si paiement annulé
    notification_url = (
        getattr(settings, "NOTIFICATION_URL", None)
        or settings.PUBLIC_BASE_URL.rstrip("/") + "/payplug/webhook"
    )

    payload = {
        "amount": amount_cents,
        "currency": "EUR",
        "save_card": False,
        "billing": {
            "email": email or "client@energyz.fr",
            "address1": address or "France",
            "first_name": client_name or "Client",
            "last_name": client_name or "",
        },
        "hosted_payment": {
            "return_url": return_url,
            "cancel_url": cancel_url,
            "sent_by": "Energyz API",
        },
        "notification_url": notification_url,
        "metadata": metadata or {},
        "description": (metadata or {}).get("description", "Paiement acompte Energyz"),
    }

    logger.info(f"[PAYPLUG] Creating payment → {payload}")

    try:
        payment = payplug.Payment.create(**payload)
        payment_url = payment.hosted_payment.payment_url
        logger.info(f"[PAYPLUG] Payment created OK url={payment_url}")
        return payment_url
    except payplug.exceptions.PayplugError as e:
        logger.error(f"[PAYPLUG] Error: {e}")
        raise
