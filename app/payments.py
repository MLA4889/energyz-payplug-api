import requests
import json
import re
from .config import settings


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", flags=re.IGNORECASE)


def _choose_api_key(iban: str) -> str:
    """Sélectionne la clé PayPlug selon l’IBAN et le mode (test/live)."""
    mode = (settings.PAYPLUG_MODE or "").lower()
    key_dict = json.loads(settings.PAYPLUG_KEYS_TEST_JSON if mode == "test" else settings.PAYPLUG_KEYS_LIVE_JSON)
    return key_dict.get((iban or "").strip())


def cents_from_str(amount_str: str) -> int:
    """Convertit un montant texte en centimes (ex: '1250.00' → 125000)."""
    try:
        if not amount_str:
            return 0
        cleaned = (
            str(amount_str)
            .replace("€", "")
            .replace("\u202f", "")
            .replace(" ", "")
            .replace(",", ".")
        )
        return int(round(float(cleaned) * 100))
    except Exception:
        return 0


def _sanitize_email(raw: str | None) -> str:
    """
    Extrait le premier email valide d'une chaîne potentiellement sale (ex: 'Nom <mail@x.y>',
    'mailto:mail@x.y', 'mail@x.y; autre@z.t', etc.). Si rien de valide: fallback.
    """
    if not raw:
        return "client@inconnu.fr"
    s = str(raw).strip()

    # Retirer 'mailto:' éventuel et chevrons
    s = s.replace("mailto:", "").replace("<", " ").replace(">", " ")

    # Remplacer séparateurs courants par espaces
    s = re.sub(r"[;,/|]", " ", s)

    # Chercher le premier motif email valide
    m = _EMAIL_RE.search(s)
    if not m:
        return "client@inconnu.fr"
    return m.group(0).lower()


def _sanitize_address_line(raw: str | None) -> str:
    """
    PayPlug est strict sur certains champs: on garantit une ligne courte et non vide.
    """
    if not raw:
        return "Adresse non précisée"
    s = str(raw).strip()
    # Éviter lignes trop longues et caractères de contrôle
    s = re.sub(r"[\r\n\t]+", " ", s)
    return s[:255] if len(s) > 255 else s


def _split_first_last(name: str | None) -> tuple[str, str]:
    """
    Découpe un nom brut en first_name / last_name acceptables pour PayPlug.
    """
    if not name:
        return ("Client", "Energyz")
    parts = str(name).strip().split()
    if len(parts) == 1:
        return (parts[0][:50], "Energyz")
    return (parts[0][:50], " ".join(parts[1:])[:50])


def create_payment(api_key: str, amount_cents: int, email: str, address: str, client_name: str, metadata: dict) -> str:
    """Crée un lien de paiement PayPlug."""
    # -- Nettoyages anti-400 PayPlug --
    email_clean = _sanitize_email(email)
    address_clean = _sanitize_address_line(address)
    first_name, last_name = _split_first_last(client_name)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "amount": amount_cents,
        "currency": "EUR",
        "customer": {
            "email": email_clean,
            "first_name": first_name,
            "last_name": last_name,
            "address1": address_clean
        },
        "metadata": metadata or {},
        "hosted_payment": {
            "return_url": settings.PUBLIC_BASE_URL
        },
        "description": (metadata or {}).get("description", "Paiement acompte Energyz")
    }

    url = "https://api.payplug.com/v1/payments"
    res = requests.post(url, headers=headers, json=payload)
    if res.status_code not in [200, 201]:
        # Log utile côté Render: renvoyer la charge postée + réponse PayPlug pour debug
        raise Exception(f"Erreur PayPlug : {res.status_code} → {res.text}")
    data = res.json()
    return data.get("hosted_payment", {}).get("payment_url")
