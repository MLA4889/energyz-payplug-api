import json
import re
from fastapi import FastAPI, Request, HTTPException

from .config import settings
from .payments import _choose_api_key, cents_from_str, create_payment
from .monday import get_item_columns, set_link_in_column, set_status

ENABLE_EVOLIZ = bool(getattr(settings, "ENABLE_EVOLIZ", False))
HAVE_EVOLIZ = False
if ENABLE_EVOLIZ:
    try:
        from .evoliz import (
            create_quote,
            extract_identifiers,
            get_or_create_public_link,
            build_app_quote_url,
            download_quote_pdf,
        )
        HAVE_EVOLIZ = True
    except Exception:
        HAVE_EVOLIZ = False

app = FastAPI(title="Energyz Payment Automation (stable)", version="3.3.0")


@app.get("/")
def root():
    return {"status": "ok", "message": "Energyz Payment Automation is live 🚀"}


def _num(text: str, default: float = 0.0) -> float:
    if not text:
        return default
    s = text.replace("€", "").replace("\u202f", "").replace(" ", "").replace(",", ".")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    try:
        return float(m.group(0)) if m else default
    except Exception:
        return default

def _from_formula(cols: dict, fid: str, fallback: float | None = None) -> float:
    # 1) text
    txt = cols.get(fid, "")
    v = _num(txt, None if fallback is None else fallback)
    if v and v > 0:
        return v
    # 2) raw JSON
    raw = cols.get(f"{fid}__raw", "")
    if raw:
        try:
            j = json.loads(raw)
            for key in ("text", "value", "label", "result"):
                val = j.get(key) if isinstance(j, dict) else None
                if isinstance(val, (int, float)) and val > 0:
                    return float(val)
                if isinstance(val, str):
                    vv = _num(val, None if fallback is None else fallback)
                    if vv and vv > 0:
                        return vv
        except Exception:
            pass
    return fallback if fallback is not None else 0.0

def _detect_acompte_num(event: dict, formula_columns: dict[str, str]) -> str | None:
    col_id = event.get("columnId", "") or ""
    # statut "Générer acompte 1/2"
    value = event.get("value")
    val_json = value if isinstance(value, dict) else None
    if isinstance(value, str):
        try:
            val_json = json.loads(value)
        except Exception:
            val_json = None
    label_text = ""
    if isinstance(val_json, dict):
        label = val_json.get("label") or {}
        label_text = (label.get("text") or "").lower().strip()
    if "générer acompte 1" in label_text:
        return "1"
    if "générer acompte 2" in label_text:
        return "2"
    # fallback: déclenchement direct depuis une colonne formule
    for k, fid in formula_columns.items():
        if fid == col_id:
            return k
    return None


@app.post("/quote/from_monday")
async def quote_from_monday(request: Request):
    try:
        payload = await request.json()
        event = payload.get("event", {})
        item_id = event.get("pulseId") or event.get("itemId")
        if not item_id:
            raise HTTPException(status_code=400, detail="Item ID manquant.")

        # IDs configurés dans l'ENV
        formula_columns = json.loads(settings.FORMULA_COLUMN_IDS_JSON)   # {"1":"formula_mkwnberr","2":"formula_mkwnntn2"}
        link_columns    = json.loads(settings.LINK_COLUMN_IDS_JSON)     # {"1":"link_mkwnz493","2":"link_mkwn3ph9"}
        status_after    = json.loads(settings.STATUS_AFTER_PAY_JSON)    # {"1":"Payé acompte 1","2":"Payé acompte 2"}

        acompte_num = _detect_acompte_num(event, formula_columns)

        # Colonnes à récupérer chez Monday
        wanted = [
            settings.EMAIL_COLUMN_ID,
            settings.ADDRESS_COLUMN_ID,
            settings.DESCRIPTION_COLUMN_ID,
            settings.IBAN_FORMULA_COLUMN_ID,
            settings.QUOTE_AMOUNT_FORMULA_ID,  # total HT util. en fallback
        ]
        # ⚠️ AJOUT CRUCIAL : on demande aussi les COLONNES FORMULE d'acompte
        wanted += list(formula_columns.values())

        for opt in (getattr(settings, "VAT_RATE_COLUMN_ID", None),
                    getattr(settings, "TOTAL_HT_COLUMN_ID", None),
                    getattr(settings, "TOTAL_TTC_COLUMN_ID", None)):
            if opt:
                wanted.append(opt)

        cols = get_item_columns(item_id, wanted)

        # Données de base
        name        = cols.get("name", "")
        email       = cols.get(settings.EMAIL_COLUMN_ID, "")
        address_txt = cols.get(settings.ADDRESS_COLUMN_ID, "")
        description = cols.get(settings.DESCRIPTION_COLUMN_ID, "") or name

        # ===== Paiements acompte 1/2 =====
        if acompte_num in ("1", "2"):
            iban   = cols.get(settings.IBAN_FORMULA_COLUMN_ID, "")
            api_key = _choose_api_key(iban)

            amount_formula_id = formula_columns.get(acompte_num)
            base_total_txt    = cols.get(getattr(settings, "TOTAL_HT_COLUMN_ID", None) or settings.QUOTE_AMOUNT_FORMULA_ID, "0")
            base_total        = _num(base_total_txt, 0.0)

            if acompte_num == "1":
                # 1) valeur de la FORMULE A1, 2) sinon fallback = HT
                amount = _from_formula(cols, amount_formula_id, fallback=base_total)
            else:
                # 1) valeur de la FORMULE A2, 2) sinon fallback = HT/2
                amount = _from_formula(cols, amount_formula_id, fallback=(base_total / 2.0 if base_total else 0.0))

            amount_cents = cents_from_str(str(amount))
            if amount_cents <= 0:
                raise HTTPException(status_code=400, detail=f"Montant invalide pour l'acompte {acompte_num}")

            pay_url = create_payment(
                api_key,
                amount_cents,
                email,
                address_txt,
                description,
                {"item_id": item_id, "acompte": acompte_num},
            )

            set_link_in_column(item_id, link_columns[acompte_num], pay_url, f"Payer acompte {acompte_num}")
            set_status(item_id, settings.STATUS_COLUMN_ID, status_after[acompte_num])

            return {"status": "ok", "type": "acompte", "acompte": acompte_num, "amount": amount, "payment_url": pay_url}

        # (Evoliz optionnel laissé tel quel, n'impacte pas les paiements)
        return {"status": "ignored", "detail": f"Colonne {event.get('columnId')} non gérée."}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== Test PayPlug sans Monday (toujours dispo) =====
@app.post("/pay/acompte/{n}")
def pay_acompte_test(n: int):
    try:
        test_iban = "FR76 1695 8000 0130 5670 5696 366"
        api_key = _choose_api_key(test_iban)
        amount_cents = cents_from_str("1250") // (2 if n == 2 else 1)
        url = create_payment(
            api_key,
            amount_cents,
            "testo@test.fr",
            "Adresse de test",
            f"Test acompte {n}",
            {"acompte": str(n), "mode": "test-endpoint"},
        )
        return {"status": "ok", "acompte": n, "payment_url": url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
