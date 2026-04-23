"""
Validation metier reutilisable : SIRET (Luhn), email, SIREN.
Toutes les fonctions renvoient des booleens ou levent ValueError.
"""
import re


_SIRET_RE = re.compile(r"^\d{14}$")
_SIREN_RE = re.compile(r"^\d{9}$")
# RFC 5322 simplifie, suffisant en pratique pour un form web
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def normalize_siret(raw: str) -> str:
    """Enleve tous les caracteres non numeriques."""
    return re.sub(r"\D", "", raw or "")


def is_valid_luhn(digits: str) -> bool:
    """
    Algorithme de Luhn sur une chaine numerique.
    Retourne True ssi la chaine est un code Luhn-valide (somme % 10 == 0).
    """
    if not digits or not digits.isdigit():
        return False
    total = 0
    # On parcourt de droite a gauche. Les positions paires (1-indexed a partir
    # de la droite) sont doublees : pour SIRET, c'est la regle utilisee par l'INSEE
    # a l'exception de La Poste (SIREN 356000000) qui utilise la regle somme-des-chiffres.
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def is_valid_siren(siren: str) -> bool:
    siren = normalize_siret(siren)
    if not _SIREN_RE.match(siren):
        return False
    # Cas special La Poste
    if siren == "356000000":
        return True
    return is_valid_luhn(siren)


def is_valid_siret(siret: str) -> bool:
    """
    Verifie qu'un SIRET est bien forme : 14 chiffres + Luhn.
    Cas particulier : les SIRET La Poste commencent par 356 0000 00 et
    n'obeissent pas a Luhn classique.
    """
    siret = normalize_siret(siret)
    if not _SIRET_RE.match(siret):
        return False
    if siret.startswith("356000000"):
        # Pour La Poste, somme simple des chiffres doit etre divisible par 5
        return sum(int(c) for c in siret) % 5 == 0
    return is_valid_luhn(siret)


def is_valid_email(email: str) -> bool:
    if not email:
        return False
    email = email.strip()
    if len(email) > 320:
        return False
    return bool(_EMAIL_RE.match(email))


def format_siret_display(siret: str) -> str:
    """Format lisible : 123 456 789 00012"""
    s = normalize_siret(siret)
    if len(s) != 14:
        return siret
    return f"{s[:3]} {s[3:6]} {s[6:9]} {s[9:]}"
