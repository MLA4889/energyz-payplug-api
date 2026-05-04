"""
Orchestrateur de facturation post-paiement.

Sequence (appelee depuis le webhook Payplug apres signature OK + paid event) :
  1) find-or-create client Evoliz par SIRET
  2) create_invoice (emission directe)
  3) register_payment (encaissement CB -> facture "payee")
  4) download PDF facture
  5) upload PDF dans la colonne Monday
  6) ecrit N° Facture + Date facturation sur Monday
  7) ecrit SIRET/Email/Raison sociale facturation sur Monday (tracabilite)
  8) passe le statut paiement a "Facture"
  9) marque le token "invoiced" dans le store
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from . import evoliz, monday, token_store
from .config import settings

logger = logging.getLogger("energyz.billing")


def run_post_payment_flow(
    token: str,
    dossier: dict[str, Any],
    paid_at_iso: str | None = None,
    payplug_payment_id: str = "",
) -> dict[str, Any]:
    """
    Orchestre toutes les etapes. Propage les exceptions : l'appelant (webhook)
    doit capturer + renvoyer 200 OK quand meme (ne pas faire retry Payplug).

    Returns:
        {
          "invoice_id": str,
          "invoice_number": str,
          "monday_file_asset_id": str | None,
          "client_created": bool,
        }
    """
    billing = dossier.get("billing") or {}
    if not billing:
        raise RuntimeError("billing manquant dans le dossier (token_store).")

    item_id = dossier["monday_item_id"]
    montant_ht = float(dossier["montant_ht"])
    montant_ttc = float(dossier["montant_ttc"])
    tva_rate = float(dossier["tva_rate"])
    prestation_label = dossier.get("prestation_label") or settings.DEFAULT_PRESTATION_LABEL
    prestation_description = dossier.get("prestation_description") or ""

    paid_date = _iso_date(paid_at_iso) or dt.date.today().isoformat()

    # --- 1) client Evoliz ---
    logger.info("[BILLING] token=%s step=find_or_create_client siret=%s", token, billing["siret"])
    client_id, created = evoliz.find_or_create_client(
        business_name=billing["raison_sociale"],
        siret=billing["siret"],
        email=billing["email"],
        address_line1=billing["adresse_ligne1"],
        address_line2=billing.get("adresse_ligne2", ""),
        postcode=billing["code_postal"],
        town=billing["ville"],
    )
    logger.info(
        "[BILLING] token=%s client_id=%s created=%s", token, client_id, created
    )

    # --- 2) facture (peut naitre en brouillon selon Evoliz) ---
    logger.info("[BILLING] token=%s step=create_invoice", token)
    invoice = evoliz.create_invoice(
        client_id=client_id,
        prestation_label=prestation_label,
        prestation_description=prestation_description,
        unit_price_ht=montant_ht,
        vat_rate=tva_rate,
        document_date=paid_date,
    )
    logger.info(
        "[BILLING] token=%s invoice_id=%s initial_status=%s",
        token, invoice["invoice_id"], invoice.get("status") or "unknown",
    )

    # --- 2b) FORCE l'emission : POST /invoices/{id}/send avec email destinataire.
    # Cet endpoint Evoliz verrouille la facture (la rend definitive : numero F-...
    # au lieu de T-...) ET envoie un email au client avec la facture en PJ.
    logger.info("[BILLING] token=%s step=issue_invoice (via /send)", token)
    issued = evoliz.issue_invoice(invoice["invoice_id"], recipient_email=billing["email"])
    if issued.get("invoice_number"):
        invoice["invoice_number"] = issued["invoice_number"]
    invoice["status"] = issued.get("status") or "issued"
    logger.info(
        "[BILLING] token=%s issued_via=%s invoice_number=%s status=%s",
        token,
        issued.get("endpoint_used"),
        invoice["invoice_number"],
        invoice["status"],
    )

    # --- 3) encaissement (sur facture emise, la passe en 'Payee') ---
    logger.info("[BILLING] token=%s step=register_payment", token)
    evoliz.register_payment(
        invoice_id=invoice["invoice_id"],
        amount_ttc=montant_ttc,
        paydate=paid_date,
        paytype="CB",
        comment=f"Paiement Payplug ref {payplug_payment_id}" if payplug_payment_id else "Paiement CB",
    )

    # --- 4) download PDF ---
    logger.info("[BILLING] token=%s step=download_pdf", token)
    try:
        pdf_bytes, filename = evoliz.download_invoice_pdf(invoice["invoice_id"])
    except Exception as e:
        logger.exception("[BILLING] token=%s PDF download failed: %s", token, e)
        pdf_bytes, filename = (b"", "")

    # --- 5) upload PDF sur Monday ---
    asset_id = None
    if pdf_bytes:
        logger.info("[BILLING] token=%s step=monday_upload_pdf size=%d", token, len(pdf_bytes))
        try:
            asset = monday.upload_file_to_column(
                item_id=item_id,
                column_id=settings.INVOICE_PDF_COLUMN_ID,
                file_bytes=pdf_bytes,
                filename=filename or f"facture_{invoice['invoice_number'] or invoice['invoice_id']}.pdf",
                mime_type="application/pdf",
            )
            asset_id = (asset or {}).get("id")
        except Exception as e:
            logger.exception("[BILLING] token=%s Monday upload failed: %s", token, e)

    # --- 6) N° Facture + Date facturation ---
    if invoice["invoice_number"]:
        _safe_monday(
            "set_invoice_number",
            monday.set_text_column,
            item_id,
            settings.INVOICE_NUMBER_COLUMN_ID,
            invoice["invoice_number"],
        )
    _safe_monday(
        "set_invoice_date",
        monday.set_date_column,
        item_id,
        settings.INVOICE_DATE_COLUMN_ID,
        paid_date,
    )

    # --- 7) tracabilite billing sur Monday ---
    _safe_monday(
        "set_billing_siret",
        monday.set_text_column,
        item_id,
        settings.BILLING_SIRET_COLUMN_ID,
        billing["siret"],
    )
    _safe_monday(
        "set_billing_email",
        monday.set_text_column,
        item_id,
        settings.BILLING_EMAIL_COLUMN_ID,
        billing["email"],
    )
    _safe_monday(
        "set_billing_legal_name",
        monday.set_text_column,
        item_id,
        settings.BILLING_LEGAL_NAME_COLUMN_ID,
        billing["raison_sociale"],
    )

    # --- 8) statut "Facture" ---
    _safe_monday(
        "set_status_invoiced",
        monday.set_status,
        item_id,
        settings.STATUS_COLUMN_ID,
        settings.STATUS_LABEL_INVOICED,
    )

    # --- 9) update token store ---
    token_store.mark_invoiced(
        token=token,
        evoliz_client_id=client_id,
        evoliz_invoice_id=invoice["invoice_id"],
        invoice_number=invoice["invoice_number"],
        invoice_date=paid_date,
    )

    return {
        "invoice_id": invoice["invoice_id"],
        "invoice_number": invoice["invoice_number"],
        "monday_file_asset_id": asset_id,
        "client_created": created,
    }


# =====================================================
# Helpers
# =====================================================

def _iso_date(iso_str: str | None) -> str | None:
    if not iso_str:
        return None
    try:
        return dt.datetime.fromisoformat(iso_str.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _safe_monday(step: str, fn, *args, **kwargs) -> None:
    """
    Wrap un appel Monday : loggue en cas d'erreur mais ne propage pas.
    Ces appels sont accessoires : on ne veut pas planter la facturation
    parce que Monday a rate une mise a jour de colonne.
    """
    try:
        fn(*args, **kwargs)
    except Exception as e:
        logger.exception("[BILLING] step=%s Monday update failed: %s", step, e)
