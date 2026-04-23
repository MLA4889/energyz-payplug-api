from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Monday
    MONDAY_API_KEY: str
    MONDAY_BOARD_ID: int

    # Evoliz (OAuth2-like: public + secret -> Bearer)
    EVOLIZ_BASE_URL: str = "https://www.evoliz.io"
    EVOLIZ_COMPANY_ID: str
    EVOLIZ_PUBLIC_KEY: str
    EVOLIZ_SECRET_KEY: str
    EVOLIZ_APP_BASE_URL: str | None = None
    EVOLIZ_TENANT_SLUG: str | None = None

    # PayPlug
    PAYPLUG_KEYS_TEST_JSON: str = "{}"
    PAYPLUG_KEYS_LIVE_JSON: str = "{}"
    PAYPLUG_MODE: str = "live"
    PAYPLUG_WEBHOOK_SECRET: str | None = None
    PUBLIC_BASE_URL: str

    # Colonnes Monday existantes (utilisees aujourd'hui)
    EMAIL_COLUMN_ID: str = ""
    ADDRESS_COLUMN_ID: str = ""
    DESCRIPTION_COLUMN_ID: str = ""
    IBAN_FORMULA_COLUMN_ID: str
    QUOTE_AMOUNT_FORMULA_ID: str
    STATUS_COLUMN_ID: str
    BUSINESS_STATUS_COLUMN_ID: str = ""
    CLIENT_TYPE_COLUMN_ID: str = ""
    SIRET_SITE_COLUMN_ID: str = ""

    # Acomptes / mapping (retrocompat)
    FORMULA_COLUMN_IDS_JSON: str = '{}'
    LINK_COLUMN_IDS_JSON: str = '{}'
    STATUS_AFTER_PAY_JSON: str = '{}'
    TRIGGER_STATUS_COLUMN_ID: str = "status"
    TRIGGER_LABELS_JSON: str = '{"1":"Generer acompte 1"}'

    # IBAN mapping fallback
    IBAN_BY_STATUS_JSON: str | None = None
    FORCE_IBAN: str | None = None

    # ==============================================================
    # Nouveau : facturation partenaire automatique
    # ==============================================================

    # Labels sur STATUS_COLUMN_ID, piloces apres evenements
    STATUS_LABEL_PAID: str = "Paye"
    STATUS_LABEL_INVOICED: str = "Facture"
    STATUS_LABEL_ERROR: str = "Bloque"

    # Colonnes Monday creees pour la facturation partenaire
    INVOICE_PDF_COLUMN_ID: str
    INVOICE_NUMBER_COLUMN_ID: str
    INVOICE_DATE_COLUMN_ID: str
    BILLING_SIRET_COLUMN_ID: str
    BILLING_EMAIL_COLUMN_ID: str
    BILLING_LEGAL_NAME_COLUMN_ID: str

    # Colonne lien paiement (on ecrit desormais l'URL de la page /p/{token})
    PAYMENT_LINK_COLUMN_ID: str  # typiquement Lien Acompte 1 (link_mkww3qd4)

    # TVA appliquee sur les factures partenaires
    DEFAULT_VAT_RATE: float = 20.0

    # Libelle de la prestation sur la facture (peut etre surchargé par item)
    DEFAULT_PRESTATION_LABEL: str = (
        "Note de dimensionnement - Destratificateur d'air"
    )

    # Duree de validite d'un token /p/{token} avant qu'il expire (jours)
    TOKEN_TTL_DAYS: int = 30

    # Storage du token: chemin sur disque (Render persistent disk recommande)
    TOKEN_STORE_PATH: str = "/tmp/token_store.json"

    # Secret partage pour appels admin (non utilise en v1)
    ADMIN_API_KEY: str | None = None

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
