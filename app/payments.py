from typing import Optional
import re
import payplug

from .config import settings


def normalize_iban(iban: str | None) -> Optional[str]:
    if not iban:
        return None
    s = iban.strip().upper()
    s = re.sub(r"\s+", "", s)
    return s or None


def _choose_api_key(iban_display_value: str | None) -> Optional[str]:
    """
    1) Normalise l'IBAN
    2) Cherche la clé correspondante selon PAYPLUG_MODE
    """
    iban_norm = normalize_iban(iban_display_value)
    if not iban_norm:
        return None
    mapping = settings.PAYPLUG_KEYS_TEST if settings.PAYPLUG_MODE == "test" else settings.PAYPLUG_KEYS_LIVE
    # Les IBAN dans l'env peuvent contenir des espaces -> normalisons aussi
    for k, v in mapping.items():
        if normalize_iban(k) == iban_norm:
            return v
    return None


def cents_from_str(val: str | float | int) -> int:
    """
    Convertit une entrée (ex: "1 234,56") en centimes.
    """
    if isinstance(val, (int, float)):
        amount = float(val)
        return int(round(amount * 100))

    s = (val or "").strip()
    s = s.replace("\u202f", "").replace(" ", "").replace(",", ".")
    if not s:
        return 0
    try:
        return int(round(float(s) * 100))
    except Exception:
        return 0


def create_payment(amount_cents: int, description: str, return_url: str) -> dict:
    if amount_cents <= 0:
        raise ValueError("Montant invalide pour PayPlug")
    # payplug secret key doit être réglée avant l'appel (voir main)
    payment = payplug.Payment.create(
        amount=amount_cents,
        currency='EUR',
        description=description[:250] if description else settings.BRAND_NAME,
        hosted_payment={
            "return_url": return_url,
        }
    )
    return payment
