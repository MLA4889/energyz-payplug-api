# app/payments.py
from typing import Optional
import re
import payplug
from .config import settings


def _variants(iban: str) -> list[str]:
    """
    Génère des variantes raisonnables de l'IBAN tel que vu côté Monday.
    Ordre de test = du plus fidèle à des versions normalisées (pour rester rétro-compatible).
    """
    if not iban:
        return []

    variants = []
    # 1) EXACT (rétro-compat “ancien code”)
    variants.append(iban)

    # 2) Normaliser espaces (simple)
    normalized_spaces = " ".join(iban.split())
    if normalized_spaces not in variants:
        variants.append(normalized_spaces)

    # 3) Sans aucun espace
    compact = re.sub(r"\s+", "", iban)
    if compact not in variants:
        variants.append(compact)

    # 4) MAJ exact
    upper_exact = iban.upper()
    if upper_exact not in variants:
        variants.append(upper_exact)

    # 5) MAJ + espaces normalisés
    upper_norm = " ".join(upper_exact.split())
    if upper_norm not in variants:
        variants.append(upper_norm)

    # 6) MAJ sans espace
    upper_compact = re.sub(r"\s+", "", upper_exact)
    if upper_compact not in variants:
        variants.append(upper_compact)

    return variants


def _choose_api_key(iban_display_value: str) -> Optional[str]:
    """
    - Essaie d'abord la correspondance EXACTE (comme ton tout premier code).
    - Puis essaie plusieurs variantes sûres.
    - S'il n'y a qu'une seule clé dans le mapping (hors AUTRE_IBAN), on l'utilise (legacy).
    - Sinon on prend AUTRE_IBAN si présent.
    """
    keymap = settings.PAYPLUG_KEYS_LIVE if settings.PAYPLUG_MODE == "live" else settings.PAYPLUG_KEYS_TEST
    if not keymap:
        return None

    # 1) essais directs (exact + variantes)
    for candidate in _variants(iban_display_value):
        if candidate and candidate in keymap:
            return keymap[candidate]

    # 2) legacy: une seule clé “réelle” → on l’utilise
    real_keys = {k: v for k, v in keymap.items() if k != "AUTRE_IBAN"}
    if len(real_keys) == 1:
        return next(iter(real_keys.values()))

    # 3) fallback générique
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
        mode = settings.PAYPLUG_MODE
        raise RuntimeError(
            f"Aucune clé PayPlug correspondante. Mode={mode}. IBAN lu='{iban_display_value}'. "
            f"Ajoute une entrée exacte dans PAYPLUG_KEYS_{'LIVE' if mode=='live' else 'TEST'}_JSON "
            f"ou fournis 'AUTRE_IBAN' comme clé par défaut."
        )

    payplug.configure(api_key)
    payment = payplug.Payment.create(
        amount=amount_cents,
        currency="EUR",
        hosted_payment={"return_url": return_url},
        notification_url=None,
        save_card=False,
        metadata={"brand": settings.BRAND_NAME, "iban": iban_display_value, "mode": settings.PAYPLUG_MODE},
        description=(description or "Acompte")[:255],
    )
    return {"id": payment.id, "url": payment.hosted_payment.payment_url, "status": payment.status}
