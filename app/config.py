from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # === Monday ===
    MONDAY_API_KEY: str
    MONDAY_BOARD_ID: int

    # === Evoliz (API) ===
    EVOLIZ_BASE_URL: str
    EVOLIZ_COMPANY_ID: str
    EVOLIZ_PUBLIC_KEY: str
    EVOLIZ_SECRET_KEY: str

    # === Evoliz (Deep-link / tenant) ===
    EVOLIZ_TENANT_SLUG: str | None = None
    EVOLIZ_APP_BASE_URL: str | None = None

    # === PayPlug ===
    PAYPLUG_KEYS_TEST_JSON: str
    PAYPLUG_KEYS_LIVE_JSON: str
    PAYPLUG_MODE: str

    # === Colonnes Monday ===
    EMAIL_COLUMN_ID: str
    ADDRESS_COLUMN_ID: str
    DESCRIPTION_COLUMN_ID: str
    DESCRIPTION_FALLBACK_COLUMN_ID: str | None = None
    IBAN_FORMULA_COLUMN_ID: str
    QUOTE_AMOUNT_FORMULA_ID: str
    LINK_COLUMN_IDS_JSON: str
    FORMULA_COLUMN_IDS_JSON: str
    STATUS_AFTER_PAY_JSON: str
    STATUS_COLUMN_ID: str

    # === Devis ===
    CREATE_QUOTE_STATUS_COLUMN_ID: str
    QUOTE_LINK_COLUMN_ID: str                 # colonne Link “Devis”
    QUOTE_FILES_COLUMN_ID: str                # colonne File “Fichiers devis”  ⬅️ NOUVEAU / À RENSEIGNER
    VAT_RATE_COLUMN_ID: str
    TOTAL_HT_COLUMN_ID: str
    TOTAL_TTC_COLUMN_ID: str

    class Config:
        env_file = ".env"


settings = Settings()
