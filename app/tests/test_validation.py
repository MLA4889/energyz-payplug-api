"""Tests : validation SIRET (Luhn) + email."""
import pytest

from app.validation import is_valid_siret, is_valid_email, normalize_siret


VALID_SIRETS = [
    "73282932000074",  # Siren Google France (exemple doc INSEE)
    "55203450200047",  # Siren classique
    "44306184100047",  # Siren valide connu
    "35600000000079",  # La Poste (cas special, sum=30 divisible par 5)
]

INVALID_SIRETS = [
    "12345678900000",  # Luhn faux
    "1234567890001",   # 13 chiffres
    "123456789000123", # 15 chiffres
    "abcdefghijklmn",  # non numerique
    "",
    None,
]


@pytest.mark.parametrize("siret", VALID_SIRETS)
def test_valid_siret(siret):
    assert is_valid_siret(siret), f"SIRET {siret} devrait etre valide"


@pytest.mark.parametrize("siret", INVALID_SIRETS)
def test_invalid_siret(siret):
    assert not is_valid_siret(siret or ""), f"SIRET {siret!r} devrait etre invalide"


def test_normalize_siret_strips_spaces_and_dashes():
    assert normalize_siret("732 829 320 00074") == "73282932000074"
    assert normalize_siret("732-829-320-00074") == "73282932000074"


@pytest.mark.parametrize("email", [
    "jean@exemple.fr",
    "compta+fact@societe-example.co.uk",
    "a@b.cd",
])
def test_valid_email(email):
    assert is_valid_email(email)


@pytest.mark.parametrize("email", [
    "",
    "pas-un-email",
    "a@b",
    "@exemple.fr",
    "x@.fr",
    "x@exemple",
])
def test_invalid_email(email):
    assert not is_valid_email(email)
