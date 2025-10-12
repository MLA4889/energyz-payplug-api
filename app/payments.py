from typing import Optional
import payplug
from .config import settings

def _choose_api_key(iban_display_value: str) -> Optional[str]:
    if settings.PAYPLUG_MODE == "test":
        return settings.PAYPLUG_KEYS_TEST.get(iban_display_value)
    return settings.PAYPLUG_KEYS_LIVE.get(iban_display_value)

def create_payment(
    api_key: str,
    amount_cents: int,
    email: str,
    address: str,
    customer_name: str,
    metadata: dict,
) -> str:
    payplug.set_secret_key(api_key)
    payment = payplug.Payment.create(
        amount=amount_cents,
        currency="EUR",
        save_card=False,
        customer={
            "email": email,
            "address1": address,
            "first_name": customer_name,
            "last_name": customer_name,
        },
        hosted_payment={
            "sent_by": "OTHER",
            "return_url": "https://monday.com",
            "cancel_url": "https://monday.com",
        },
        notification_url=f"{settings.PUBLIC_BASE_URL}/pay/notify",
        metadata=metadata,
    )
    return payment.hosted_payment.payment_url

def cents_from_str(euro_str: str) -> int:
    if not euro_str:
        return 0
    euro_str = euro_str.replace(" ", "").replace(",", ".")
    return int(round(float(euro_str) * 100))
