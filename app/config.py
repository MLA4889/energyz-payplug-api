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
    PUBLIC_BASE_URL: str

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

    # Optionnel : forcer un IBAN
    FORCE_IBAN: str | None = None

settings = Settings()
