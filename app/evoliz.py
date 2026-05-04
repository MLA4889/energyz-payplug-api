"""
Client Evoliz pour la facturation automatique post-paiement.

Logique :
  1) auth via public_key + secret_key -> token Bearer
  2) find_or_create_client (match par SIRET)
  3) create_invoice avec un item (prestation + montant HT + TVA)
  4) issue_invoice (emission) puis register_payment (encaissement CB)
  5) download_invoice_pdf

SIRET = cle unique. On ne matche jamais par nom (trop volatile).
"""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Any, Optional

import requests

from .config import settings


# =====================================================
# Auth
# =====================================================

_SESSION: dict[str, Any] = {"token": None, "expires_at": 0.0}


def _login() -> str:
    url = f"{settings.EVOLIZ_BASE_URL}/api/login"
    r = requests.post(
        url,
        json={
            "public_key": settings.EVOLIZ_PUBLIC_KEY,
            "secret_key": settings.EVOLIZ_SECRET_KEY,
        },
        headers={"Content-Type": "application/json"},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    token = data.get("access_token") or data.get("token")
    if not token:
        raise RuntimeError(f"Evoliz login: token manquant dans la reponse: {data}")
    # Les tokens Evoliz expirent typiquement en 1h. On re-login 5 min avant.
    ttl = int(data.get("expires_in", 3300))
    _SESSION["token"] = token
    _SESSION["expires_at"] = time.time() + max(ttl - 300, 60)
    return token


def _headers(content_type: str | None = "application/json") -> dict[str, str]:
    if not _SESSION["token"] or time.time() >= _SESSION["expires_at"]:
        _login()
    h = {"Authorization": f"Bearer {_SESSION['token']}"}
    if content_type:
        h["Content-Type"] = content_type
    return h


def _request(
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    params: dict | None = None,
    expect_json: bool = True,
) -> Any:
    url = f"{settings.EVOLIZ_BASE_URL}{path}"
    r = requests.request(
        method,
        url,
        headers=_headers(),
        json=json_body,
        params=params,
        timeout=25,
    )
    if r.status_code == 401:
        _login()
        r = requests.request(
            method,
            url,
            headers=_headers(),
            json=json_body,
            params=params,
            timeout=25,
        )
    if not r.ok:
        raise RuntimeError(f"Evoliz {method} {path} -> {r.status_code}: {r.text}")
    return r.json() if expect_json else r.content


def _companies_path(suffix: str) -> str:
    return f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}{suffix}"


# =====================================================
# Clients (find-or-create par SIRET)
# =====================================================

def _extract_id(obj: dict) -> Optional[str]:
    for k in ("clientid", "client_id", "id"):
        if obj.get(k) is not None:
            return str(obj[k])
    data = obj.get("data")
    if isinstance(data, dict):
        return _extract_id(data)
    return None


def find_client_by_siret(siret: str) -> Optional[str]:
    """Retourne l'id Evoliz du client dont le SIRET matche exactement."""
    siret = (siret or "").strip()
    if not siret:
        return None
    try:
        data = _request("GET", _companies_path("/clients"), params={"search": siret})
    except Exception:
        return None
    items = data if isinstance(data, list) else data.get("data") or []
    for it in items:
        if str(it.get("siret") or "").replace(" ", "") == siret.replace(" ", ""):
            return _extract_id(it)
    return None


def create_client(
    business_name: str,
    siret: str,
    email: str,
    address_line1: str,
    address_line2: str,
    postcode: str,
    town: str,
    country_iso: str = "FR",
) -> str:
    """
    Cree un client professionnel et retourne son id.

    Format Evoliz API v1 (verifie sur erreur 400) :
      - type : "Company" ou "Individual" (capitalise)
      - name : raison sociale (required)
      - address.iso2 : code pays ISO-3166-1 alpha-2 (pas "iso")
    """
    # Pour un client Professionnel FR, Evoliz attend (decouvert via 400) :
    #   - type = "Professionnel"
    #   - business_identification_number = SIREN (9 chiffres)
    #   - business_number = numero RCS / SIRET complet (libre)
    #   - vat_number = "FR" + cle 2-chiffres + SIREN (calculee)
    siret_clean = "".join(c for c in (siret or "") if c.isdigit())
    siren = siret_clean[:9] if len(siret_clean) >= 9 else ""
    vat_number = _compute_fr_vat(siren) if siren else ""

    address: dict = {
        "addr": str(address_line1 or "Adresse non precisee"),
        "postcode": str(postcode or "00000"),
        "town": str(town or "N/A"),
        "iso2": str(country_iso or "FR"),
    }
    # Evoliz refuse string vide pour addr2 -> on l'omet plutot que d'envoyer ""
    if address_line2 and str(address_line2).strip():
        address["addr2"] = str(address_line2).strip()

    payload = {
        "type": "Professionnel",
        "name": str(business_name or ""),
        "business_identification_number": siren,
        "business_number": siret_clean,
        "vat_number": vat_number,
        "mail": str(email or ""),
        "address": address,
    }
    data = _request("POST", _companies_path("/clients"), json_body=payload)
    client_id = _extract_id(data)
    if not client_id:
        raise RuntimeError(f"Evoliz create_client: id introuvable dans {data}")
    return client_id


def _compute_fr_vat(siren: str) -> str:
    """
    Calcule le numero de TVA intracommunautaire FR a partir du SIREN.
    Formule : cle = (12 + 3 * (SIREN mod 97)) mod 97
    Resultat : 'FR' + cle (2 chiffres) + SIREN
    """
    siren_clean = "".join(c for c in (siren or "") if c.isdigit())
    if len(siren_clean) != 9:
        return ""
    n = int(siren_clean)
    key = (12 + 3 * (n % 97)) % 97
    return f"FR{key:02d}{siren_clean}"


def find_or_create_client(
    business_name: str,
    siret: str,
    email: str,
    address_line1: str,
    address_line2: str,
    postcode: str,
    town: str,
) -> tuple[str, bool]:
    """
    Retourne (client_id, created) ou created=True si nouveau.
    """
    existing = find_client_by_siret(siret)
    if existing:
        return existing, False
    new_id = create_client(
        business_name=business_name,
        siret=siret,
        email=email,
        address_line1=address_line1,
        address_line2=address_line2,
        postcode=postcode,
        town=town,
    )
    return new_id, True


# =====================================================
# Factures
# =====================================================

def create_invoice(
    client_id: str,
    prestation_label: str,
    prestation_description: str,
    unit_price_ht: float,
    vat_rate: float,
    document_date: str | None = None,
) -> dict[str, Any]:
    """
    Cree une facture emise (status=issued) pour un client.
    documentdate au format YYYY-MM-DD.
    """
    documentdate = document_date or dt.date.today().isoformat()
    designation = (prestation_label or "Prestation").strip()
    description = (prestation_description or "").strip()
    payload = {
        "clientid": int(client_id) if str(client_id).isdigit() else client_id,
        "documentdate": documentdate,
        "status": "issued",
        "term": {"paytermid": 1},  # paiement immediat
        "items": [
            {
                "designation": designation,
                "description": description,
                "quantity": 1,
                "unit_price": round(float(unit_price_ht), 2),
                "vat_rate": round(float(vat_rate), 2),
            }
        ],
    }
    data = _request("POST", _companies_path("/invoices"), json_body=payload)
    body = data.get("data") if isinstance(data, dict) and "data" in data else data
    invoice_id = str(body.get("invoiceid") or body.get("id") or "")
    invoice_number = str(body.get("document_number") or body.get("number") or body.get("invoicenumber") or "")
    pdf_url = body.get("pdf_url") or body.get("pdf") or ""
    status = str(body.get("status") or "").lower()
    if not invoice_id:
        raise RuntimeError(f"Evoliz create_invoice: id manquant dans {body}")
    return {
        "invoice_id": invoice_id,
        "invoice_number": invoice_number,
        "pdf_url": pdf_url,
        "status": status,
        "raw": body,
    }


def issue_invoice(invoice_id: str, recipient_email: str = "") -> dict[str, Any]:
    """
    Emet la facture (= la passe de brouillon a definitive) ET l'envoie par email
    au client.

    Endpoint reel Evoliz API decouvert : POST /invoices/{id}/send
    Cet appel verrouille la facture (la rend definitive, lui donne un numero
    final F-... au lieu de T-...) et envoie un email au destinataire.

    Args:
        invoice_id : id Evoliz de la facture
        recipient_email : email destinataire (obligatoire pour /send)

    Si recipient_email est vide ou si /send est indisponible, on retombe sur
    un GET pour verifier que la facture est dans un etat acceptable.
    """
    if recipient_email:
        try:
            data = _request(
                "POST",
                _companies_path(f"/invoices/{invoice_id}/send"),
                json_body={"to": [recipient_email]},
            )
            body = data.get("data") if isinstance(data, dict) and "data" in data else data
            return {
                "invoice_id": invoice_id,
                "invoice_number": str(
                    body.get("document_number")
                    or body.get("number")
                    or body.get("invoicenumber")
                    or ""
                ),
                "status": str(body.get("status") or "sent").lower(),
                "endpoint_used": "/send",
                "raw": body,
            }
        except RuntimeError as e:
            last_err: Exception = e
    else:
        last_err = RuntimeError("recipient_email manquant pour /send")

    # Fallback : refetcher pour voir l'etat actuel (peut-etre deja emise)
    try:
        data = _request("GET", _companies_path(f"/invoices/{invoice_id}"))
        body = data.get("data") if isinstance(data, dict) and "data" in data else data
        return {
            "invoice_id": invoice_id,
            "invoice_number": str(
                body.get("document_number")
                or body.get("number")
                or body.get("invoicenumber")
                or ""
            ),
            "status": str(body.get("status") or "").lower(),
            "endpoint_used": "get_invoice_fallback",
            "raw": body,
        }
    except Exception:
        raise RuntimeError(
            f"Evoliz issue_invoice {invoice_id} echec : {last_err}"
        )


def register_payment(
    invoice_id: str,
    amount_ttc: float,
    paydate: str | None = None,
    paytype: str = "CB",
    comment: str = "",
) -> dict[str, Any]:
    """Enregistre un encaissement sur une facture (la passe en 'Payee')."""
    payload = {
        "paydate": paydate or dt.date.today().isoformat(),
        "paytype": paytype,
        "amount": round(float(amount_ttc), 2),
        "comment": comment or "",
    }
    path = _companies_path(f"/invoices/{invoice_id}/payments")
    data = _request("POST", path, json_body=payload)
    return data if isinstance(data, dict) else {"data": data}


def download_invoice_pdf(invoice_id: str) -> tuple[bytes, str]:
    """
    Telecharge le PDF d'une facture. Essaye plusieurs endpoints connus.
    Retourne (bytes, filename).
    """
    candidates = [
        _companies_path(f"/invoices/{invoice_id}/pdf"),
        _companies_path(f"/invoices/{invoice_id}/download"),
        _companies_path(f"/invoices/{invoice_id}/export/pdf"),
    ]
    last_err: Exception | None = None
    for path in candidates:
        url = f"{settings.EVOLIZ_BASE_URL}{path}"
        try:
            r = requests.get(url, headers=_headers(content_type=None), timeout=60)
            if r.status_code == 401:
                _login()
                r = requests.get(url, headers=_headers(content_type=None), timeout=60)
            if not r.ok:
                last_err = RuntimeError(f"GET {path} -> {r.status_code}: {r.text[:200]}")
                continue
            filename = f"facture_{invoice_id}.pdf"
            cd = r.headers.get("content-disposition", "")
            m = re.search(r'filename="?([^";]+)"?', cd)
            if m:
                filename = m.group(1).strip()
            return r.content, filename
        except requests.RequestException as e:
            last_err = e
            continue
    raise RuntimeError(f"Impossible de telecharger le PDF {invoice_id}: {last_err}")
