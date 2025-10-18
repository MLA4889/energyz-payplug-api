import datetime as dt
from typing import Optional, Tuple, Dict, Any
import re

import requests
from .config import settings

SESSION = {"token": None}


def _login() -> str:
    url = f"{settings.EVOLIZ_BASE_URL}/api/login"
    r = requests.post(
        url,
        json={"public_key": settings.EVOLIZ_PUBLIC_KEY, "secret_key": settings.EVOLIZ_SECRET_KEY},
        headers={"Content-Type": "application/json"},
        timeout=25,
    )
    r.raise_for_status()
    data = r.json()
    token = data.get("access_token") or data.get("token")
    if not token:
        raise Exception(f"Evoliz login: token missing in response: {data}")
    SESSION["token"] = token
    return token


def _headers() -> dict:
    if not SESSION["token"]:
        _login()
    return {"Authorization": f"Bearer {SESSION['token']}", "Content-Type": "application/json"}


def _request(method: str, path: str, payload: dict | None = None):
    url = f"{settings.EVOLIZ_BASE_URL}{path}"
    r = requests.request(method, url, headers=_headers(), json=payload or {}, timeout=25)
    if r.status_code == 401:
        _login()
        r = requests.request(method, url, headers=_headers(), json=payload or {}, timeout=25)
    if not r.ok:
        raise Exception(f"Evoliz API error {r.status_code}: {r.text}")
    return r.json()


def _post(path: str, payload: dict | None = None):
    return _request("POST", path, payload)


def _get_bytes(path: str) -> tuple[bytes, str | None]:
    """
    GET binaire (PDF). Retourne (content, content-disposition).
    """
    url = f"{settings.EVOLIZ_BASE_URL}{path}"
    h = _headers()
    # file download: ne pas forcer JSON
    h.pop("Content-Type", None)
    r = requests.get(url, headers=h, timeout=60)
    if r.status_code == 401:
        _login()
        h = _headers()
        h.pop("Content-Type", None)
        r = requests.get(url, headers=h, timeout=60)
    r.raise_for_status()
    return r.content, r.headers.get("content-disposition")


# === (tes fonctions ensure_recipient/create_quote/extract_identifiers/build_app_quote_url, etc.) ===
# ... (garde le contenu que nous avons déjà en place, y compris get_or_create_public_link) ...


# ---------- NOUVEAU : téléchargement du PDF d’un devis ----------
def download_quote_pdf(qid: str) -> tuple[bytes, str]:
    """
    Tente plusieurs endpoints PDF connus.
    Retourne (pdf_bytes, filename).
    """
    candidates = [
        f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes/{qid}/pdf",
        f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes/{qid}/download",
    ]
    last_err = None
    for path in candidates:
        try:
            content, cd = _get_bytes(path)
            # filename depuis Content-Disposition
            filename = f"devis_{qid}.pdf"
            if cd:
                m = re.search(r'filename="?([^"]+)"?', cd)
                if m:
                    filename = m.group(1)
            return content, filename
        except Exception as e:
            last_err = e
    raise Exception(f"Impossible de récupérer le PDF du devis {qid}: {last_err}")
