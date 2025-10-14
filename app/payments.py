from typing import Optional
from .config import settings


def _choose_api_key(iban_display_value: str) -> Optional[str]:
    """
    Choisit la clé PayPlug selon l'IBAN (en mode live ou test).
    Si aucun IBAN ne matche, on tente la clé 'AUTRE_IBAN' si elle existe.
    """
    keymap = settings.PAYPLUG_KEYS_LIVE if settings.PAYPLUG_MODE == "live" else settings.PAYPLUG_KEYS_TEST
    if not iban_display_value:
        return keymap.get("AUTRE_IBAN")
    k = " ".join(iban_display_value.split())  # normalise espaces
    return keymap.get(k) or keymap.get("AUTRE_IBAN")


def cents_from_str(s: str | None) -> int:
    if not s:
        return 0
    s = s.replace("€", "").replace(" ", "").replace(",", ".")
    try:
        return int(round(float(s) * 100))
    except Exception:
        return 0


def _configure_payplug(api_key: str):
    """
    Rendre la config compatible avec plusieurs versions du SDK PayPlug:
    - Ancien: payplug.configure(secret)
    - Variante: payplug.set_api_key(secret)
    - Nouveau: payplug.configuration = payplug.Configuration(secret_key=secret)
    - Fallback très ancien: payplug.config = {'secret_key': secret}
    Retourne le module payplug configuré.
    """
    try:
        import payplug  # import ici pour éviter un import au démarrage si pas installé
    except Exception as e:
        raise RuntimeError(f"PayPlug non installé ou import impossible: {e}")

    try:
        if hasattr(payplug, "configure"):
            payplug.configure(api_key)  # type: ignore[attr-defined]
            return payplug

        if hasattr(payplug, "set_api_key"):
            payplug.set_api_key(api_key)  # type: ignore[attr-defined]
            return payplug

        if hasattr(payplug, "Configuration"):
            # Nouveau style
            payplug.configuration = payplug.Configuration(secret_key=api_key)  # type: ignore[attr-defined]
            return payplug

        # Très vieux style
        if hasattr(payplug, "config"):
            payplug.config = {"secret_key": api_key}  # type: ignore[attr-defined]
            return payplug

        raise RuntimeError("Aucune méthode de configuration PayPlug compatible trouvée.")
    except Exception as e:
        raise RuntimeError(f"Erreur configuration PayPlug: {e}")


def create_payment(amount_cents: int, description: str, return_url: str, iban_display_value: str) -> dict:
    api_key = _choose_api_key(iban_display_value)
    if not api_key:
        mode = settings.PAYPLUG_MODE
        raise RuntimeError(
            f"Aucune clé PayPlug correspondante. Mode={mode}. IBAN lu='{iban_display_value}'. "
            "Ajoute l'IBAN exact dans PAYPLUG_KEYS_*_JSON ou fournis 'AUTRE_IBAN' par défaut."
        )

    payplug = _configure_payplug(api_key)

    # Sanitize description (PayPlug limite à 255 chars)
    desc = (description or "Acompte")[:255]

    # Selon les versions du SDK, la classe Payment est au même endroit
    Payment = getattr(payplug, "Payment", None)
    if Payment is None or not hasattr(Payment, "create"):
        raise RuntimeError("SDK PayPlug inattendu: 'Payment.create' est introuvable.")

    payment = Payment.create(
        amount=amount_cents,
        currency="EUR",
        hosted_payment={"return_url": return_url},
        notification_url=None,
        save_card=False,
        metadata={"brand": settings.BRAND_NAME, "iban": iban_display_value, "mode": settings.PAYPLUG_MODE},
        description=desc,
    )

    # Rendre la réponse homogène
    payment_id = getattr(payment, "id", None) or getattr(payment, "payment_id", None)
    hosted = getattr(payment, "hosted_payment", None)
    url = None
    if hosted and hasattr(hosted, "payment_url"):
        url = hosted.payment_url
    elif isinstance(payment, dict):
        # au cas où la lib renverrait un dict
        url = payment.get("hosted_payment", {}).get("payment_url")
        payment_id = payment.get("id", payment_id)
    if not url:
        # essai ultime
        url = getattr(payment, "payment_url", None)

    status = getattr(payment, "status", None) or (payment.get("status") if isinstance(payment, dict) else None)

    return {"id": payment_id, "url": url, "status": status}
