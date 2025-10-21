from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Monday
    MONDAY_API_KEY: str
    MONDAY_BOARD_ID: int

    # Evoliz (compat)
    EVOLIZ_BASE_URL: str
    EVOLIZ_COMPANY_ID: str
    EVOLIZ_PUBLIC_KEY: str
    EVOLIZ_SECRET_KEY: str

    # PayPlug
    PAYPLUG_KEYS_TEST_JSON: str
    PAYPLUG_KEYS_LIVE_JSON: str
    PAYPLUG_MODE: str
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
    CLIENT_TYPE_COLUMN_ID: str

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

    # ------------------------ Bridge (PIS) ------------------------
    BRIDGE_BASE_URL: str              # ex: https://api.bridgeapi.io
    BRIDGE_VERSION: str               # ex: 2025-01-15
    BRIDGE_CLIENT_ID: str             # sandbox_id_...
    BRIDGE_CLIENT_SECRET: str         # sandbox_secret_...
    BRIDGE_SUCCESS_URL: str           # https://www.energyz.fr
    BRIDGE_CANCEL_URL: str            # https://www.energyz.fr/cancel
    BRIDGE_WEBHOOK_SECRET: str        # dev-test (ou autre)

    BRIDGE_BENEFICIARY_NAME: str      # ENERGYZ
    BRIDGE_BENEFICIARY_IBAN: str      # FR76 1695 8000 0100 0571 1982 492

settings = Settings()
