from typing import Optional
import payplug
from .config import settings

def _choose_api_key(iban_display_value: str) -> Optional[str]:
    keymap = settings.PAYPLUG_KEYS_LIVE if settings.PAYPLUG_MODE == "live" else settings.PAYPLUG_KEYS_TEST
    if not iban_display_value:
        return keymap.get("AUTRE_IBAN")
    k = " ".join(iban_display_value.split())
    return keymap.get(k) or keymap.get("AUTRE_IBAN")

def cents_from_str(s: str | None) -> int:
    if not s:
        return 0
    s = s.replace("€", "").replace(" ", "").replace(",", ".")
    try:
        return int(round(float(s) * 100))
    except Exception:
        return 0

def create_payment(amount_cents: int, description: str, return_url: str, iban_display_value: str) -> dict:
    api_key = _choose_api_key(iban_display_value)
    if not api_key:
        raise RuntimeError("Aucune clé PayPlug correspondante à l'IBAN sélectionné.")
    payplug.configure(api_key)
    payment = payplug.Payment.create(
        amount=amount_cents,
        currency='EUR',
        hosted_payment={'return_url': return_url},
        notification_url=None,
        save_card=False,
        metadata={"brand": settings.BRAND_NAME, "iban": iban_display_value, "mode": settings.PAYPLUG_MODE},
        description=(description or "Acompte")[:255],
    )
    return {"id": payment.id, "url": payment.hosted_payment.payment_url, "status": payment.status}
