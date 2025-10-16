from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    MONDAY_API_KEY: str
    MONDAY_BOARD_ID: str
    PUBLIC_BASE_URL: str

    EVOLIZ_PUBLIC_KEY: str
    EVOLIZ_SECRET_KEY: str
    EVOLIZ_COMPANY_ID: str
    EVOLIZ_BASE_URL: str = "https://www.evoliz.io"

    PAYPLUG_MODE: str = "test"
    PAYPLUG_KEYS_JSON: str = "{}"
    PAYPLUG_KEYS_TEST_JSON: str = "{}"

    class Config:
        env_file = ".env"

settings = Settings()
