from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # === Monday ===
    MONDAY_API_KEY: str
    MONDAY_BOARD_ID: int

    # === Evoliz (API) ===
    EVOLIZ_BASE_URL: str           # ex: https://www.evoliz.io
    EVOLIZ_COMPANY_ID: str         # ex: 101457-128860 (CHAÎNE)
    EVOLIZ_PUBLIC_KEY: str
    EVOLIZ_SECRET_KEY: str

    # === Evoliz (Deep-link / tenant) ===
    # Si tu as un slug locataire (ex: energyz), ça permet de construire un deep-link
    EVOLIZ_TENANT_SLUG: str | None = None          # ex: "energyz"
    EVOLIZ_APP_BASE_URL: str | None = None         # ex: https://app.evoliz.com

    # === PayPlug ===
    PAYPLUG_KEYS_TEST_JSON: str
    PAYPLUG_KEYS_LIVE_JSON: str
    PAYPLUG_MODE: str

    # === Colonnes Monday ===
    EMAIL_COLUMN_ID: str
    ADDRESS_COLUMN_ID: str
    DESCRIPTION_COLUMN_ID: str                     # "Description presta" (formula)
    DESCRIPTION_FALLBACK_COLUMN_ID: str | None = None
    IBAN_FORMULA_COLUMN_ID: str
    QUOTE_AMOUNT_FORMULA_ID: str
    LINK_COLUMN_IDS_JSON: str                      # {"1":"link_id_acompte_1","2":"link_id_acompte_2"}
    FORMULA_COLUMN_IDS_JSON: str                   # {"1":"formula_acompte_1","2":"formula_acompte_2"}
    STATUS_AFTER_PAY_JSON: str                     # {"1":"Payé acompte 1","2":"Payé acompte 2"}
    STATUS_COLUMN_ID: str

    # === Devis ===
    CREATE_QUOTE_STATUS_COLUMN_ID: str             # colonne status "Créer devis"
    QUOTE_LINK_COLUMN_ID: str                      # colonne link "Devis"
    QUOTE_FILES_COLUMN_ID: str                     # colonne file "Fichiers devis"
    VAT_RATE_COLUMN_ID: str                        # "TVA"
    TOTAL_HT_COLUMN_ID: str                        # "Montant total HT"
    TOTAL_TTC_COLUMN_ID: str                       # "Montant total TTC"

    class Config:
        env_file = ".env"


settings = Settings()
