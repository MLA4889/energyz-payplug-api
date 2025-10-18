from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # === Monday ===
    MONDAY_API_KEY: str
    MONDAY_BOARD_ID: int

    # === Evoliz (API principale) ===
    EVOLIZ_BASE_URL: str                 # ex: https://www.evoliz.io
    EVOLIZ_COMPANY_ID: str
    EVOLIZ_PUBLIC_KEY: str
    EVOLIZ_SECRET_KEY: str

    # === Evoliz (Application / Lien public) ===
    # Si ton compte Evoliz utilise une URL de type https://evoliz.com/energyz/quote/display.php?QUOTEID=xxxx
    # alors tu dois définir EVOLIZ_TENANT_SLUG="energyz"
    # L’API construira automatiquement : https://evoliz.com/energyz/quote/display.php?QUOTEID=<ID>
    EVOLIZ_TENANT_SLUG: str | None = None

    # Si ton compte utilise plutôt https://app.evoliz.com, garde cette variable :
    EVOLIZ_APP_BASE_URL: str | None = None

    # === PayPlug ===
    PAYPLUG_KEYS_TEST_JSON: str
    PAYPLUG_KEYS_LIVE_JSON: str
    PAYPLUG_MODE: str                    # "test" ou "live"

    # === Colonnes Monday ===
    EMAIL_COLUMN_ID: str
    ADDRESS_COLUMN_ID: str
    DESCRIPTION_COLUMN_ID: str           # ta colonne Formula "Description presta"
    DESCRIPTION_FALLBACK_COLUMN_ID: str | None = None  # colonne Texte de secours
    IBAN_FORMULA_COLUMN_ID: str
    QUOTE_AMOUNT_FORMULA_ID: str
    LINK_COLUMN_IDS_JSON: str
    FORMULA_COLUMN_IDS_JSON: str
    STATUS_AFTER_PAY_JSON: str
    STATUS_COLUMN_ID: str

    # === Devis Evoliz ===
    CREATE_QUOTE_STATUS_COLUMN_ID: str   # colonne Status "Créer devis"
    QUOTE_LINK_COLUMN_ID: str            # colonne Lien "Devis"
    VAT_RATE_COLUMN_ID: str
    TOTAL_HT_COLUMN_ID: str
    TOTAL_TTC_COLUMN_ID: str

    class Config:
        env_file = ".env"


# Instance unique globale
settings = Settings()
