from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Monday
    MONDAY_API_KEY: str
    MONDAY_BOARD_ID: int

    # PayPlug
    PAYPLUG_KEYS_TEST_JSON: str
    PAYPLUG_KEYS_LIVE_JSON: str
    PAYPLUG_MODE: str  # "test" | "live"

    # Colonnes Monday (paiements)
    EMAIL_COLUMN_ID: str
    ADDRESS_COLUMN_ID: str
    DESCRIPTION_COLUMN_ID: str
    IBAN_FORMULA_COLUMN_ID: str
    QUOTE_AMOUNT_FORMULA_ID: str
    LINK_COLUMN_IDS_JSON: str           # {"1":"link_xxx","2":"link_yyy"}
    FORMULA_COLUMN_IDS_JSON: str        # {"1":"formula_acompte1","2":"formula_acompte2"}
    STATUS_AFTER_PAY_JSON: str          # {"1":"Payé acompte 1","2":"Payé acompte 2"}
    STATUS_COLUMN_ID: str

    # Devis (OPTIONNEL – ne bloquera jamais les acomptes)
    ENABLE_EVOLIZ: bool = False
    CREATE_QUOTE_STATUS_COLUMN_ID: str | None = None
    QUOTE_LINK_COLUMN_ID: str | None = None
    QUOTE_FILES_COLUMN_ID: str | None = None
    VAT_RATE_COLUMN_ID: str | None = None
    TOTAL_HT_COLUMN_ID: str | None = None
    TOTAL_TTC_COLUMN_ID: str | None = None

    # Evoliz (OPTIONNEL si ENABLE_EVOLIZ=True)
    EVOLIZ_BASE_URL: str | None = None
    EVOLIZ_APP_BASE_URL: str | None = None
    EVOLIZ_COMPANY_ID: str | None = None
    EVOLIZ_PUBLIC_KEY: str | None = None
    EVOLIZ_SECRET_KEY: str | None = None
    EVOLIZ_TENANT_SLUG: str | None = None

    class Config:
        env_file = ".env"


settings = Settings()
