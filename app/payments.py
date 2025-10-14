# app/payments.py
from typing import Optional
import re
import payplug
from .config import settings

def _sanitize_iban(s: str) -> str:
    if not s:
        return ""
    s = s.upper()
    s = re.sub(r"[^A-Z0-9]", "", s)  # enlève tous les séparateurs/espaces
    return s

def _variants(iban: str) -> list[str]:
    """Renvoie plusieurs variantes plausibles: avec espaces groupe 4, sans espaces, originale."""
    if not iban:
        return []
    # sans espaces
    v1 = _sanitize_iban(iban)
    # avec espaces tous les 4
    v2 = " ".join([v1[i:i+4] for i in range(0, len(v1), 4)])
    # format 4-4-... peut exister, mais on ne l'ajoute pas pour éviter des faux-positifs
    return [iban, v1, v2]

def _choose_api_key(iban_display_value: str) -> Optional[str]:
    keymap = settings.PAYPLUG_KEYS_LIVE if settings.PAYPLUG_MODE == "live" else settings.PAYPLUG_KEYS_TEST
    if not keymap:
        return None

    # essaie variantes
    for candidate in _variants(iban_display_value):
        if candidate and candidate in keymap:
            return keymap[candidate]

    # fallback
    return keymap.get("AUTRE_IBAN")

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
        # message d'erreur détaillé pour debug
        mode = settings.PAYPLUG_MODE
        raise RuntimeError(
            f"Aucune clé PayPlug trouvée. Mode={mode}. IBAN lu='{iban_display_value}'. "
            f"Ajoute la clé dans PAYPLUG_KEYS_{'LIVE' if mode=='live' else 'TEST'}_JSON ou renseigne AUTRE_IBAN."
        )
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
