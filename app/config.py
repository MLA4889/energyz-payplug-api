from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONDAY_API_KEY: str
    MONDAY_BOARD_ID: int

    EVOLIZ_BASE_URL: str
    EVOLIZ_COMPANY_ID: str
    EVOLIZ_PUBLIC_KEY: str
    EVOLIZ_SECRET_KEY: str

    PAYPLUG_MODE: str
    PAYPLUG_KEYS_TEST_JSON: str
    PAYPLUG_KEYS_LIVE_JSON: str
    PUBLIC_BASE_URL: str

    ADDRESS_COLUMN_ID: str
    EMAIL_COLUMN_ID: str
    DESCRIPTION_COLUMN_ID: str
    VAT_RATE_COLUMN_ID: str
    VAT_NUMBER_COLUMN_ID: str
    DOC_FILES_COLUMN_ID: str
    STATUS_COLUMN_ID: str
    CLIENT_TYPE_COLUMN_ID: str
    BUSINESS_STATUS_COLUMN_ID: str
    QUOTE_LINK_COLUMN_ID: str
    QUOTE_AMOUNT_FORMULA_ID: str
    FORMULA_COLUMN_IDS_JSON: str
    LINK_COLUMN_IDS_JSON: str
    STATUS_AFTER_PAY_JSON: str
    IBAN_BY_STATUS_JSON: str
    IBAN_FORMULA_COLUMN_ID: str
    DEFAULT_VAT_RATE: int = 20

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
