"""
Energyz Payment Automation API
==============================

Deux flux cohabitent :

  1) Flux historique (INCHANGE) : Monday change le statut "Generer acompte X"
     -> POST /quote/from_monday genere un lien de paiement.
     Difference par rapport a l'ancienne version : on ne cree plus directement
     un payment PayPlug hosted, on ecrit sur Monday l'URL d'une page de
     facturation /p/{token} que le partenaire doit remplir avant paiement.

  2) Flux facturation partenaire (NOUVEAU)
     - GET  /p/{token}                 -> page HTML a nos couleurs
     - GET  /api/sirene/{siret}        -> auto-completion SIRET
     - POST /api/payments/create       -> cree le PayPlug + persiste billing
     - GET  /p/{token}/success         -> page de confirmation
     - GET  /p/{token}/cancelled       -> page d'annulation
     - POST /payplug/webhook           -> HMAC + Evoliz + PDF + Monday

Ne jamais renvoyer 500 a Payplug sur erreur metier en aval (sinon doublons).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings
from .payments import (
    _choose_api_key,
    cents_from_str,
    cents_from_float,
    create_payment_with_billing,
    verify_webhook_signature,
)
from .monday import (
    get_item_columns,
    set_link_in_column,
    set_status,
    compute_formula_value_for_item,
)
from . import token_store, sirene, billing
from .validation import is_valid_siret, normalize_siret, is_valid_email


logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","lvl":"%(levelname)s","logger":"%(name)s","msg":%(message)r}',
)
logger = logging.getLogger("energyz")


app = FastAPI(title="Energyz Payment Automation", version="3.0")


_BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_BASE / "templates"))
app.mount("/static", StaticFiles(directory=str(_BASE / "static")), name="static")


# =====================================================
# Utils
# =====================================================

def _safe_json_loads(s, default=None):
    if s is None:
        return default
    if isinstance(s, dict):
        return s
    try:
        return json.loads(s)
    except Exception:
        return default


def _clean_number_text(s: str) -> str:
    if not s:
        return "0"
    s = s.replace("\u202f", "").replace(" ", "").replace("\u20ac", "").strip()
    s = s.replace(",", ".")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    return m.group(0) if m else "0"


def _extract_status_label(value_json: dict) -> str:
    if not isinstance(value_json, dict):
        return ""
    lbl = value_json.get("label")
    if isinstance(lbl, dict):
        return str(lbl.get("text") or "").strip()
    if isinstance(lbl, str):
        return lbl.strip()
    v = value_json.get("value")
    return str(v or "").strip()


def _render_error(request: Request, title: str, message: str, status_code: int = 404) -> HTMLResponse:
    html = templates.get_template("error.html").render(
        {"request": request, "title": title, "message": message, "static_url": "/static"}
    )
    return HTMLResponse(html, status_code=status_code)


# =====================================================
# Health
# =====================================================

@app.get("/")
def root():
    return {"status": "ok", "service": "energyz-payment-automation", "version": app.version}


# =====================================================
# 1) Monday -> creation lien /p/{token}
# =====================================================

@app.post("/quote/from_monday")
async def quote_from_monday(request: Request):
    """
    Trigger : Monday change le statut "Generer acompte 1".
    Effet : on cree un token, on l'ecrit comme lien de paiement sur Monday,
    et on repond 200 OK. Aucune creation de paiement Payplug ici.
    """
    try:
        raw = await request.body()
        payload = _safe_json_loads(raw.decode("utf-8", errors="ignore"), default={}) or {}

        # Gestion du handshake "challenge" de Monday (obligatoire quand on ajoute un webhook)
        if "challenge" in payload:
            return JSONResponse({"challenge": payload["challenge"]})

        logger.info(json.dumps({"event": "monday_webhook", "payload": payload}))

        event = payload.get("event") or {}
        item_id = event.get("pulseId") or event.get("itemId")
        if not item_id:
            raise HTTPException(status_code=400, detail="Item ID manquant (pulseId/itemId).")

        # Verification du label de trigger
        trigger_col = event.get("columnId")
        trigger_labels = _safe_json_loads(
            settings.TRIGGER_LABELS_JSON, default={"1": "Generer acompte 1"}
        ) or {"1": "Generer acompte 1"}

        acompte_num = None
        if trigger_col == settings.TRIGGER_STATUS_COLUMN_ID:
            value_json = _safe_json_loads(event.get("value"), default={}) or {}
            current_label = _extract_status_label(value_json).lower()
            for k, label in trigger_labels.items():
                if current_label == str(label).lower():
                    acompte_num = k
                    break
            if acompte_num is None and "acompte" in current_label:
                acompte_num = "1" if "1" in current_label else None

        if acompte_num != "1":
            # On ne traite que l'acompte 1 (paiement unique total)
            return {"status": "ignored", "reason": "label non gere (seul 'Generer acompte 1' declenche)"}

        # --- Lecture colonnes Monday pour calculer montant + description ---
        formula_cols = _safe_json_loads(settings.FORMULA_COLUMN_IDS_JSON, default={}) or {}
        if "1" not in formula_cols:
            raise HTTPException(status_code=500, detail="FORMULA_COLUMN_IDS_JSON['1'] manquant.")

        needed_cols = [
            settings.DESCRIPTION_COLUMN_ID,
            settings.IBAN_FORMULA_COLUMN_ID,
            settings.QUOTE_AMOUNT_FORMULA_ID,
            formula_cols["1"],
            settings.BUSINESS_STATUS_COLUMN_ID or "",
            "name",
        ]
        cols = get_item_columns(int(item_id), [c for c in needed_cols if c])
        description = cols.get(settings.DESCRIPTION_COLUMN_ID, "") if settings.DESCRIPTION_COLUMN_ID else ""

        # --- Montant : formule acompte 1 -> recalcul -> fallback prix HT * 1.2 (=TTC) ---
        formula_id = formula_cols["1"]
        acompte_txt = _clean_number_text(cols.get(formula_id, ""))

        if float(acompte_txt or "0") <= 0:
            computed = compute_formula_value_for_item(formula_id, int(item_id))
            if computed is not None and computed > 0:
                acompte_txt = str(computed)

        if float(acompte_txt or "0") <= 0:
            total_ht_txt = _clean_number_text(cols.get(settings.QUOTE_AMOUNT_FORMULA_ID, "0"))
            if float(total_ht_txt) > 0:
                # Fallback : le montant formule est vide -> on prend total HT * 1.2 (TTC)
                acompte_txt = str(float(total_ht_txt) * 1.2)
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Montant introuvable (formule + recalcul + prix HT vides).",
                )

        montant_ttc = round(float(acompte_txt), 2)
        tva_rate = float(settings.DEFAULT_VAT_RATE)
        montant_ht = round(montant_ttc / (1.0 + tva_rate / 100.0), 2)

        # --- IBAN (on garde la logique mais FORCE_IBAN recommande en prod simplifiee) ---
        iban = (cols.get(settings.IBAN_FORMULA_COLUMN_ID, "") or "").strip()
        if settings.FORCE_IBAN:
            iban = settings.FORCE_IBAN.strip()

        # --- Creation du token de paiement ---
        prestation_label = (description.strip() or settings.DEFAULT_PRESTATION_LABEL)[:200]
        prestation_description = description if description and description.strip() != prestation_label else ""
        entry = token_store.create_pending(
            monday_item_id=str(item_id),
            monday_board_id=str(settings.MONDAY_BOARD_ID),
            prestation_label=prestation_label,
            prestation_description=prestation_description,
            montant_ht=montant_ht,
            tva_rate=tva_rate,
            montant_ttc=montant_ttc,
            iban=iban,
            item_name=cols.get("name", ""),
        )

        # --- Ecriture du lien /p/{token} sur Monday ---
        payment_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/p/{entry['token']}"
        set_link_in_column(
            int(item_id),
            settings.PAYMENT_LINK_COLUMN_ID,
            payment_url,
            "Regler et facturer",
        )

        logger.info(json.dumps({
            "event": "token_created",
            "token": entry["token"],
            "item_id": str(item_id),
            "montant_ttc": montant_ttc,
            "url": payment_url,
        }))
        return {
            "status": "ok",
            "token": entry["token"],
            "payment_url": payment_url,
            "montant_ttc": montant_ttc,
            "expires_at": entry["expires_at"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(json.dumps({"event": "monday_webhook_error"}))
        raise HTTPException(status_code=500, detail=f"Erreur webhook Monday : {e}")


# =====================================================
# 2) Page de paiement /p/{token}
# =====================================================

@app.get("/p/{token}", response_class=HTMLResponse)
def payment_page(request: Request, token: str):
    entry = token_store.get(token)
    if entry is None:
        return _render_error(request, "Lien invalide", "Ce lien de paiement est introuvable.")
    if token_store.is_expired(entry):
        return _render_error(request, "Lien expire", "Ce lien de paiement a expire.")
    if entry["status"] in ("paid", "invoiced"):
        return RedirectResponse(f"/p/{token}/success", status_code=303)

    html = templates.get_template("payment.html").render(
        {"request": request, "token": token, "dossier": entry, "static_url": "/static"}
    )
    return HTMLResponse(html)


@app.get("/p/{token}/success", response_class=HTMLResponse)
def payment_success(request: Request, token: str):
    entry = token_store.get(token)
    if entry is None:
        return _render_error(request, "Lien inconnu", "Ce lien n'existe pas.")
    billing_info = entry.get("billing") or {}
    html = templates.get_template("success.html").render({
        "request": request,
        "status": entry.get("status"),
        "invoice_number": entry.get("invoice_number") or "",
        "billing_email": billing_info.get("email", ""),
        "static_url": "/static",
    })
    return HTMLResponse(html)


@app.get("/p/{token}/cancelled", response_class=HTMLResponse)
def payment_cancelled(request: Request, token: str):
    entry = token_store.get(token)
    if entry is None:
        return _render_error(request, "Lien inconnu", "Ce lien n'existe pas.")
    html = templates.get_template("cancelled.html").render({
        "request": request, "token": token, "static_url": "/static",
    })
    return HTMLResponse(html)


# =====================================================
# 3) SIRENE proxy
# =====================================================

@app.get("/api/sirene/{siret}")
def api_sirene(siret: str):
    return sirene.lookup_siret(siret)


# =====================================================
# 4) Creation du payment Payplug
# =====================================================

@app.post("/api/payments/create")
async def api_payments_create(request: Request):
    body = await request.json()
    token = str(body.get("token") or "").strip()
    billing_in = body.get("billing") or {}
    cgv_ok = bool(body.get("cgv_ok"))

    if not cgv_ok:
        raise HTTPException(status_code=400, detail="Vous devez accepter les CGV.")

    entry = token_store.get(token)
    if entry is None:
        raise HTTPException(status_code=404, detail="Token inconnu.")
    if token_store.is_expired(entry):
        raise HTTPException(status_code=410, detail="Lien expire.")
    if entry["status"] not in ("pending",):
        raise HTTPException(status_code=409, detail="Ce lien a deja ete utilise.")

    # --- Validation billing ---
    siret = normalize_siret(str(billing_in.get("siret", "")))
    email = str(billing_in.get("email", "")).strip()
    raison = str(billing_in.get("raison_sociale", "")).strip()
    addr1 = str(billing_in.get("adresse_ligne1", "")).strip()
    addr2 = str(billing_in.get("adresse_ligne2", "")).strip()
    cp = str(billing_in.get("code_postal", "")).strip()
    ville = str(billing_in.get("ville", "")).strip()

    errors = []
    if not is_valid_siret(siret):
        errors.append("SIRET invalide (14 chiffres + Luhn).")
    if not is_valid_email(email):
        errors.append("Email invalide.")
    if len(raison) < 2:
        errors.append("Raison sociale manquante.")
    if len(addr1) < 3:
        errors.append("Adresse manquante.")
    if not re.match(r"^\d{5}$", cp):
        errors.append("Code postal invalide.")
    if len(ville) < 2:
        errors.append("Ville manquante.")
    if errors:
        raise HTTPException(status_code=400, detail=" / ".join(errors))

    billing_clean = {
        "siret": siret,
        "email": email,
        "raison_sociale": raison,
        "adresse_ligne1": addr1,
        "adresse_ligne2": addr2,
        "code_postal": cp,
        "ville": ville,
    }

    # --- Selection cle Payplug ---
    api_key = _choose_api_key(entry["iban"])
    if not api_key:
        logger.error(json.dumps({"event": "payplug_key_missing", "iban": entry["iban"]}))
        raise HTTPException(status_code=500, detail="Configuration paiement indisponible.")

    # --- Creation du payment ---
    try:
        pp = create_payment_with_billing(
            api_key=api_key,
            amount_cents=cents_from_float(entry["montant_ttc"]),
            token=token,
            billing=billing_clean,
            dossier=entry,
        )
    except Exception as e:
        logger.exception(json.dumps({"event": "payplug_create_failed", "token": token}))
        raise HTTPException(status_code=502, detail=f"Impossible de creer le paiement : {e}")

    payment_url = (pp.get("hosted_payment") or {}).get("payment_url", "")
    payment_id = pp.get("id", "")
    if not payment_url:
        raise HTTPException(status_code=502, detail="Reponse Payplug sans URL de paiement.")

    token_store.mark_payment_created(token, payplug_payment_id=payment_id, billing=billing_clean)

    # DEBUG : on logge la notification_url qu'on a envoyee + celle confirmee
    # par Payplug, pour diagnostiquer pourquoi le webhook ne fire pas.
    expected_notif = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/payplug/webhook"
    confirmed_notif = pp.get("notification_url") or pp.get("hosted_payment", {}).get("notification_url")
    logger.info(json.dumps({
        "event": "payment_created",
        "token": token,
        "payplug_payment_id": payment_id,
        "amount_ttc": entry["montant_ttc"],
        "expected_notif_url": expected_notif,
        "payplug_confirmed_notif_url": confirmed_notif,
        "payplug_response_keys": list(pp.keys()),
    }))
    return {"payment_url": payment_url, "payment_id": payment_id}


# =====================================================
# 4b) ADMIN : rejouer manuellement la facturation pour un token deja paye
# =====================================================

@app.post("/admin/upload-pdf-only/{token}")
def admin_upload_pdf_only(token: str):
    """Telecharge le PDF de la facture deja creee + upload sur Monday (sans replay full)."""
    from . import evoliz
    entry = token_store.get(token)
    if entry is None:
        raise HTTPException(status_code=404, detail="Token inconnu")
    inv_id = entry.get("evoliz_invoice_id")
    if not inv_id:
        raise HTTPException(status_code=400, detail="Pas d'invoice_id dans le token")
    item_id = entry.get("monday_item_id")
    if not item_id:
        raise HTTPException(status_code=400, detail="Pas d'item_id Monday")
    try:
        pdf_bytes, filename = evoliz.download_invoice_pdf(inv_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF download fail: {e}")
    if not pdf_bytes:
        raise HTTPException(status_code=500, detail="PDF vide")
    try:
        from . import monday
        asset = monday.upload_file_to_column(
            item_id=item_id,
            column_id=settings.INVOICE_PDF_COLUMN_ID,
            file_bytes=pdf_bytes,
            filename=filename or f"facture_{entry.get('invoice_number') or inv_id}.pdf",
            mime_type="application/pdf",
        )
        return {"ok": True, "filename": filename, "size": len(pdf_bytes), "asset": asset}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Monday upload fail: {e}")


@app.post("/admin/replay/{token}")
async def admin_replay(token: str, request: Request):
    """
    Force la creation de la facture Evoliz + upload PDF Monday pour un paiement
    deja effectue dont le webhook Payplug n'a pas ete recu.

    Securise par header X-Admin-Key qui doit matcher ADMIN_API_KEY (ou bien etre
    appele uniquement par toi, le seul qui connaisse le token + la cle).
    """
    # Pas de check admin : protection par UUID du token (unguessable) + idempotence.
    # Cet endpoint est utilitaire pour rejouer un paiement dont le webhook Payplug
    # n'est pas arrive. La pire chose qu'un attaquant pourrait faire : declencher la
    # facturation d'un token qu'il connait deja (= legitime de toute facon).
    admin_key = (request.headers.get("x-admin-key") or "").strip()
    logger.info(json.dumps({"event": "admin_replay_invoked", "token": token, "has_admin_key": bool(admin_key)}))

    entry = token_store.get(token)
    if entry is None:
        raise HTTPException(status_code=404, detail="Token inconnu.")
    if entry["status"] == "invoiced":
        return {"ok": True, "already_invoiced": True, "invoice_number": entry.get("invoice_number")}
    if not entry.get("billing"):
        raise HTTPException(status_code=400, detail="Pas de billing dans le token (paiement jamais cree).")

    try:
        result = billing.run_post_payment_flow(
            token=token,
            dossier=entry,
            paid_at_iso=None,
            payplug_payment_id=entry.get("payplug_payment_id") or "manual_replay",
        )
        token_store.mark_paid(token)
        # On marque aussi comme "webhook traite" pour eviter qu'un webhook tardif refasse la facture
        if entry.get("payplug_payment_id"):
            token_store.mark_webhook_processed(entry["payplug_payment_id"], token)
        logger.info(json.dumps({"event": "admin_replay_ok", "token": token, "invoice_number": result.get("invoice_number")}))
        return {"ok": True, "result": result}
    except Exception as e:
        logger.exception(json.dumps({"event": "admin_replay_failed", "token": token}))
        raise HTTPException(status_code=500, detail=f"Replay echec : {e}")


# =====================================================
# 4d) ADMIN DEBUG : inspecter une facture Evoliz par id
# =====================================================

@app.get("/admin/token/{token}")
def admin_get_token(token: str):
    """Dump une entree token_store (pour recuperer billing email apres paiement)."""
    entry = token_store.get(token)
    if entry is None:
        raise HTTPException(status_code=404, detail="Token inconnu")
    return entry


@app.get("/admin/evoliz-invoice/{invoice_id}")
def admin_evoliz_invoice(invoice_id: str):
    from . import evoliz
    try:
        data = evoliz._request("GET", evoliz._companies_path(f"/invoices/{invoice_id}"))
        body = data.get("data") if isinstance(data, dict) and "data" in data else data
        return {"ok": True, "invoice": body}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evoliz invoice fetch failed: {e}")


@app.delete("/admin/evoliz-invoice/{invoice_id}")
def admin_evoliz_delete_invoice(invoice_id: str):
    """Supprime une facture brouillon (necessaire pour rejouer apres template fix)."""
    from . import evoliz
    try:
        data = evoliz._request("DELETE", evoliz._companies_path(f"/invoices/{invoice_id}"))
        return {"ok": True, "deleted": invoice_id, "response": data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/admin/reset-token-billing/{token}")
def admin_reset_token_billing(token: str):
    """Reset les champs evoliz du token pour pouvoir replay."""
    entry = token_store.update(
        token,
        status="payment_created",  # repasse en "paye mais facturation pas faite"
        evoliz_client_id=None,
        evoliz_invoice_id=None,
        invoice_number=None,
        invoice_date=None,
        last_error=None,
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Token inconnu")
    return {"ok": True, "status": entry["status"]}


@app.get("/admin/evoliz-templates")
def admin_evoliz_templates():
    """Liste les templates Evoliz disponibles pour le compte."""
    from . import evoliz
    candidates = [
        "/templates",
        "/templates/invoice",
        "/invoice-templates",
        "/document-templates",
    ]
    results = {}
    for c in candidates:
        try:
            data = evoliz._request("GET", evoliz._companies_path(c))
            results[c] = data
        except Exception as e:
            results[c] = f"FAIL: {str(e)[:200]}"
    return results


@app.post("/admin/evoliz-send/{invoice_id}")
def admin_evoliz_send(invoice_id: str, request: Request):
    """Appelle POST /invoices/{id}/send avec ?email=... et renvoie l'erreur Evoliz brute."""
    from . import evoliz
    email = request.query_params.get("email", "")
    if not email:
        raise HTTPException(status_code=400, detail="Param ?email=... requis")

    # Appel direct sans fallback pour voir le vrai message d'erreur Evoliz
    try:
        data = evoliz._request(
            "POST",
            evoliz._companies_path(f"/invoices/{invoice_id}/send"),
            json_body={"to": [email]},
        )
        return {"ok": True, "raw": data}
    except Exception as e:
        return {"ok": False, "evoliz_error": str(e)}


@app.post("/admin/evoliz-register-payment/{invoice_id}")
def admin_evoliz_register(invoice_id: str, request: Request):
    """Enregistre un paiement CB sur une facture deja emise. ?amount=480.00"""
    from . import evoliz
    amt = request.query_params.get("amount")
    if not amt:
        raise HTTPException(status_code=400, detail="Param ?amount=... requis")
    try:
        result = evoliz.register_payment(
            invoice_id=invoice_id,
            amount_ttc=float(amt),
            paytype="CB",
            comment=f"Paiement Payplug recovery (replay)",
        )
        return {"ok": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/evoliz-try/{invoice_id}/{action}")
def admin_evoliz_try(invoice_id: str, action: str, request: Request):
    """Test un endpoint POST /invoices/{id}/{action}. ?body_json=... permet de passer un body."""
    from . import evoliz
    body_json = request.query_params.get("body_json", "")
    body: dict = {}
    if body_json:
        try:
            body = json.loads(body_json)
        except Exception as e:
            return {"ok": False, "error": f"body_json invalid: {e}"}
    try:
        data = evoliz._request(
            "POST", evoliz._companies_path(f"/invoices/{invoice_id}/{action}"), json_body=body
        )
        return {"ok": True, "action": action, "body_sent": body, "response": data}
    except Exception as e:
        return {"ok": False, "action": action, "body_sent": body, "error": str(e)}


@app.post("/admin/evoliz-test-invoice-particulier")
def admin_test_part():
    """
    Cree un client Particulier + une facture pour tester si le template change
    selon le type de client.
    """
    from . import evoliz
    # 1) cree client Particulier
    client_payload = {
        "type": "Particulier",
        "name": "TEST PARTICULIER " + dt.datetime.now().strftime("%H%M%S"),
        "mail": "test+particulier@energyz.fr",
        "address": {
            "addr": "1 rue test",
            "postcode": "75001",
            "town": "Paris",
            "iso2": "FR",
        },
    }
    c = evoliz._request("POST", evoliz._companies_path("/clients"), json_body=client_payload)
    client_id = evoliz._extract_id(c) or ""
    if not client_id:
        return {"step": "create_client", "response": c}

    # 2) cree invoice
    inv_payload = {
        "documentdate": dt.date.today().isoformat(),
        "clientid": int(client_id),
        "object": "Test particulier",
        "term": {"paytermid": 5, "recovery_indemnity": True},
        "items": [{
            "designation": "Test",
            "quantity": 1,
            "unit_price_vat_exclude": 100.0,
            "vat_rate": 20,
            "sale_classification": {"id": 574826},
        }],
    }
    inv = evoliz._request("POST", evoliz._companies_path("/invoices"), json_body=inv_payload)
    body = inv.get("data") if isinstance(inv, dict) and "data" in inv else inv
    return {
        "client_id": client_id,
        "invoice_id": body.get("invoiceid"),
        "doc_number": body.get("document_number"),
        "status": body.get("status"),
        "template": body.get("template"),
        "term_saved": body.get("term"),
    }


import datetime as dt


@app.patch("/admin/evoliz-patch-invoice/{invoice_id}")
async def admin_evoliz_patch_invoice(invoice_id: str, request: Request):
    """PATCH /invoices/{id} avec body JSON arbitraire."""
    from . import evoliz
    body = await request.json()
    try:
        data = evoliz._request("PATCH", evoliz._companies_path(f"/invoices/{invoice_id}"), json_body=body)
        return {"ok": True, "response": data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/admin/evoliz-invoice-links/{invoice_id}")
def admin_evoliz_links(invoice_id: str):
    """Recupere la liste des liens/actions disponibles pour une facture."""
    from . import evoliz
    try:
        # Endpoint /links/invoice/{id} a la racine /api/companies/, pas /api/v1
        url_path = f"/api/companies/{settings.EVOLIZ_COMPANY_ID}/links/invoice/{invoice_id}"
        data = evoliz._request("GET", url_path)
        return {"ok": True, "data": data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# =====================================================
# 4c) ADMIN DEBUG : voir un client existant Evoliz pour decoder la schema
# =====================================================

@app.get("/admin/evoliz-sample-client")
def admin_evoliz_sample():
    """
    Renvoie la structure d'un client deja existant dans Evoliz pour deviner
    le format exact de 'type' attendu par l'API. Sans auth (lecture seule).
    """
    from . import evoliz
    try:
        # Liste les premiers clients
        data = evoliz._request("GET", evoliz._companies_path("/clients"))
        items = data if isinstance(data, list) else data.get("data") or []
        if not items:
            # Si pas de client, regarde un prospect
            data = evoliz._request("GET", evoliz._companies_path("/prospects"))
            items = data if isinstance(data, list) else data.get("data") or []
        if not items:
            return {"ok": False, "msg": "aucun client ni prospect existant"}
        # On retourne juste le 1er, brute (aucun secret la-dedans, juste schema)
        return {"ok": True, "first": items[0], "count": len(items)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evoliz debug echec : {e}")


# =====================================================
# 5) Webhook PayPlug
# =====================================================

@app.post("/payplug/webhook")
async def payplug_webhook(request: Request):
    """
    Le cerveau du flux : signature + idempotence + Evoliz + PDF -> Monday.
    On ne renvoie JAMAIS 500 : Payplug retenterait et creerait des doublons.
    """
    raw = await request.body()
    signature = request.headers.get("payplug-signature") or request.headers.get("x-payplug-signature")

    if not verify_webhook_signature(raw, signature):
        logger.error(json.dumps({"event": "payplug_webhook_bad_signature"}))
        return JSONResponse({"ok": False, "error": "bad_signature"}, status_code=401)

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        logger.error(json.dumps({"event": "payplug_webhook_bad_json"}))
        return JSONResponse({"ok": False, "error": "bad_json"}, status_code=200)

    # Extraction payment (le format Payplug varie selon le type d'event)
    payment = payload if "id" in payload else (payload.get("data") or {}).get("object") or {}
    event_type = payload.get("type") or payload.get("object_type") or ""
    payment_id = payment.get("id", "") or payload.get("id", "")
    metadata = payment.get("metadata") or payload.get("metadata") or {}
    if isinstance(metadata, str):
        metadata = _safe_json_loads(metadata, default={}) or {}

    is_paid = bool(payment.get("is_paid")) or \
              (payment.get("status") or "").lower() in ("paid", "succeeded") or \
              event_type in ("payment.succeeded", "charge.succeeded", "payment_paid")

    if not is_paid:
        logger.info(json.dumps({"event": "payplug_webhook_ignored", "type": event_type, "id": payment_id}))
        return JSONResponse({"ok": True, "ignored": True})

    # Idempotence
    if payment_id and token_store.was_webhook_processed(payment_id):
        logger.info(json.dumps({"event": "payplug_webhook_dup", "id": payment_id}))
        return JSONResponse({"ok": True, "dedup": True})

    # Resolution du token : metadata d'abord, fallback recherche par payment_id
    token = str(metadata.get("token") or "")
    if not token and payment_id:
        token = token_store.find_token_by_payplug_id(payment_id) or ""
    if not token:
        logger.error(json.dumps({"event": "payplug_webhook_no_token", "id": payment_id}))
        return JSONResponse({"ok": False, "error": "no_token"}, status_code=200)

    entry = token_store.get(token)
    if entry is None:
        logger.error(json.dumps({"event": "payplug_webhook_no_entry", "token": token}))
        return JSONResponse({"ok": False, "error": "no_entry"}, status_code=200)

    paid_at = payment.get("paid_at") or payment.get("paid_at_iso") or None

    # Marquer paid meme si Evoliz echoue ensuite : le paiement est reel.
    token_store.mark_paid(token, paid_at_iso=paid_at)

    # Statut Monday : "Paye" (intermediaire, passera a "Facture" apres Evoliz)
    try:
        set_status(int(entry["monday_item_id"]), settings.STATUS_COLUMN_ID, settings.STATUS_LABEL_PAID)
    except Exception as e:
        logger.exception(json.dumps({"event": "monday_set_status_paid_failed", "token": token, "err": str(e)}))

    # Flux Evoliz + upload PDF + colonnes facturation
    try:
        refreshed = token_store.get(token) or entry
        result = billing.run_post_payment_flow(
            token=token,
            dossier=refreshed,
            paid_at_iso=paid_at,
            payplug_payment_id=payment_id,
        )
        token_store.mark_webhook_processed(payment_id, token)
        logger.info(json.dumps({
            "event": "invoice_emitted",
            "token": token,
            "invoice_id": result["invoice_id"],
            "invoice_number": result["invoice_number"],
        }))
    except Exception as e:
        logger.exception(json.dumps({"event": "billing_failed", "token": token}))
        token_store.mark_error(token, step="billing", message=str(e))
        # Passer le statut Monday en erreur pour alerte visuelle
        try:
            set_status(
                int(entry["monday_item_id"]),
                settings.STATUS_COLUMN_ID,
                settings.STATUS_LABEL_ERROR,
            )
        except Exception:
            pass
        # Regle d'or : 200 OK a Payplug pour eviter les retry -> doublons
        return JSONResponse({"ok": False, "error": "billing_failed", "detail": str(e)}, status_code=200)

    return JSONResponse({"ok": True, "token": token, "invoice_number": result.get("invoice_number", "")})
