"""
Configure les variables d'environnement minimales pour que app.config charge
sans acces a une prod reelle.

Note : pytest collecte ce fichier avant d'importer tout module 'app.*', donc
les env vars sont en place avant que pydantic-settings instancie Settings().
"""
import os

os.environ.setdefault("MONDAY_API_KEY", "test_monday_key")
os.environ.setdefault("MONDAY_BOARD_ID", "1234567890")
os.environ.setdefault("EVOLIZ_COMPANY_ID", "1")
os.environ.setdefault("EVOLIZ_PUBLIC_KEY", "test_pub")
os.environ.setdefault("EVOLIZ_SECRET_KEY", "test_sec")
os.environ.setdefault("PUBLIC_BASE_URL", "http://localhost:8000")
os.environ.setdefault("IBAN_FORMULA_COLUMN_ID", "formula_iban")
os.environ.setdefault("QUOTE_AMOUNT_FORMULA_ID", "numeric_total")
os.environ.setdefault("STATUS_COLUMN_ID", "status_col")
os.environ.setdefault("INVOICE_PDF_COLUMN_ID", "file_pdf")
os.environ.setdefault("INVOICE_NUMBER_COLUMN_ID", "text_num")
os.environ.setdefault("INVOICE_DATE_COLUMN_ID", "date_inv")
os.environ.setdefault("BILLING_SIRET_COLUMN_ID", "text_siret")
os.environ.setdefault("BILLING_EMAIL_COLUMN_ID", "text_email")
os.environ.setdefault("BILLING_LEGAL_NAME_COLUMN_ID", "text_legal")
os.environ.setdefault("PAYMENT_LINK_COLUMN_ID", "link_paiement")
os.environ.setdefault("PAYPLUG_KEYS_LIVE_JSON", "{\"FR76 0000\":\"sk_live_test\"}")
os.environ.setdefault("PAYPLUG_KEYS_TEST_JSON", "{\"FR76 0000\":\"sk_test_test\"}")
os.environ.setdefault("PAYPLUG_MODE", "test")
os.environ.setdefault("PAYPLUG_WEBHOOK_SECRET", "")
os.environ.setdefault("TOKEN_STORE_PATH", "/tmp/energyz_test_tokens.json")
