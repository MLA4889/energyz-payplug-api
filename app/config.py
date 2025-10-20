from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Monday
    MONDAY_API_KEY: str
    MONDAY_BOARD_ID: int

    # Evoliz (compat éventuellement)
    EVOLIZ_BASE_URL: str | None = None
    EVOLIZ_COMPANY_ID: str | None = None
    EVOLIZ_PUBLIC_KEY: str | None = None
    EVOLIZ_SECRET_KEY: str | None = None

    # PayPlug
    PAYPLUG_KEYS_TEST_JSON: str  # {"FR76 ....366":"sk_test_xxx", "FR76 ....492":"sk_test_yyy"}
    PAYPLUG_KEYS_LIVE_JSON: str  # {"FR76 ....366":"sk_live_xxx", "FR76 ....492":"sk_live_yyy"}
    PAYPLUG_MODE: str            # "test" | "live"
    PUBLIC_BASE_URL: str         # ex: "https://energyz-payplug-api-1.onrender.com"

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
    FORMULA_COLUMN_IDS_JSON: str   # {"1":"formula_xxx_acompte1","2":"formula_yyy_acompte2"}
    LINK_COLUMN_IDS_JSON: str      # {"1":"link_col_for_a1","2":"link_col_for_a2"}
    STATUS_AFTER_PAY_JSON: str     # {"1":"Payé acompte 1","2":"Payé acompte 2"}
    TRIGGER_STATUS_COLUMN_ID: str  # status column id qui déclenche la création du lien
    TRIGGER_LABELS_JSON: str       # {"1":"Acompte 1","2":"Acompte 2"}

    # IBAN mapping fallback
    IBAN_BY_STATUS_JSON: str | None = None

    # (Optionnel) forcer un IBAN
    FORCE_IBAN: str | None = None

settings = Settings()
