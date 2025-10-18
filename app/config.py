from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Monday
    MONDAY_API_KEY: str
    MONDAY_BOARD_ID: int

    # Evoliz
    EVOLIZ_BASE_URL: str          # ex: https://www.evoliz.io
    EVOLIZ_COMPANY_ID: str        # ex: 101457-128860
    EVOLIZ_PUBLIC_KEY: str
    EVOLIZ_SECRET_KEY: str

    # Payplug
    PAYPLUG_KEYS_TEST_JSON: str
    PAYPLUG_KEYS_LIVE_JSON: str
    PAYPLUG_MODE: str

    # Monday Column IDs
    EMAIL_COLUMN_ID: str
    ADDRESS_COLUMN_ID: str
    DESCRIPTION_COLUMN_ID: str
    IBAN_FORMULA_COLUMN_ID: str
    QUOTE_AMOUNT_FORMULA_ID: str
    LINK_COLUMN_IDS_JSON: str
    FORMULA_COLUMN_IDS_JSON: str
    STATUS_AFTER_PAY_JSON: str
    STATUS_COLUMN_ID: str

    # Devis (NEW)
    CREATE_QUOTE_STATUS_COLUMN_ID: str   # colonne “Créer devis” (status)
    QUOTE_LINK_COLUMN_ID: str            # colonne “Devis” (link)
    VAT_RATE_COLUMN_ID: str              # TVA (numbers)
    VAT_NUMBER_COLUMN_ID: str            # TVA intracom (text) - optionnel
    TOTAL_HT_COLUMN_ID: str              # Montant total HT (numbers)
    TOTAL_TTC_COLUMN_ID: str             # Montant total TTC (numbers) - utilisé en secours

    PUBLIC_BASE_URL: str = "https://energyz-payplug-api-1.onrender.com"

    class Config:
        env_file = ".env"

settings = Settings()
