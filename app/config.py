# src/app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Monday
    MONDAY_API_KEY: str
    MONDAY_BOARD_ID: int

    # Evoliz (compat)
    EVOLIZ_BASE_URL: str | None = None
    EVOLIZ_COMPANY_ID: str | None = None
    EVOLIZ_PUBLIC_KEY: str | None = None
    EVOLIZ_SECRET_KEY: str | None = None

    # PayPlug
    PAYPLUG_KEYS_TEST_JSON: str
    PAYPLUG_KEYS_LIVE_JSON: str
    PAYPLUG_MODE: str = "test"
    PUBLIC_BASE_URL: str  # ex: https://energyz-payplug-api.onrender.com
    NOTIFICATION_URL: str | None = None  # ex: https://.../payplug/webhook (optionnel)

    # Colonnes Monday
    EMAIL_COLUMN_ID: str
    ADDRESS_COLUMN_ID: str
    DESCRIPTION_COLUMN_ID: str
    IBAN_FORMULA_COLUMN_ID: str
    QUOTE_AMOUNT_FORMULA_ID: str
    STATUS_COLUMN_ID: str
    BUSINESS_STATUS_COLUMN_ID: str
    CLIENT_TYPE_COLUMN_ID: str | None = None

    # Acomptes / mapping
    FORMULA_COLUMN_IDS_JSON: str
    LINK_COLUMN_IDS_JSON: str
    STATUS_AFTER_PAY_JSON: str
    TRIGGER_STATUS_COLUMN_ID: str
    TRIGGER_LABELS_JSON: str

    # IBAN mapping fallback
    IBAN_BY_STATUS_JSON: str | None = None

    # Checkout comportement (laisse vide pour obliger la saisie côté PayPlug)
    FORCE_CHECKOUT_COLLECT_CONTACT: str | None = None

    # ---------- Bridge (virement) ----------
    BRIDGE_CLIENT_ID: str | None = None
    BRIDGE_CLIENT_SECRET: str | None = None
    BRIDGE_VERSION: str | None = None
    BRIDGE_BASE_URL: str | None = None
    BRIDGE_SUCCESS_URL: str | None = None
    BRIDGE_CANCEL_URL: str | None = None
    BRIDGE_WEBHOOK_SECRET: str | None = None
    BRIDGE_BENEFICIARY_NAME: str | None = None
    BRIDGE_BENEFICIARY_IBAN: str | None = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
