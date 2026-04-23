"""
Resolution SIRET -> donnees entreprise via l'API publique recherche-entreprises.
Avantages : pas d'authentification necessaire, quotas large, donnees unifiees.

Docs : https://recherche-entreprises.api.gouv.fr/
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any

from .validation import is_valid_siret, normalize_siret


BASE_URL = "https://recherche-entreprises.api.gouv.fr/search"
TIMEOUT = 8.0


def lookup_siret(siret: str) -> dict[str, Any]:
    """
    Retourne un dict unifie :
    {
      "found": bool,
      "siret": str,
      "raison_sociale": str,
      "adresse_ligne1": str,
      "adresse_ligne2": str,
      "code_postal": str,
      "ville": str,
      "actif": bool,
    }
    En cas de SIRET invalide ou introuvable, "found" = False et les autres
    champs sont a chaine vide. Ne leve jamais d'exception sauf si l'API
    distante est indisponible.
    """
    siret_norm = normalize_siret(siret)
    if not is_valid_siret(siret_norm):
        return {"found": False, "reason": "invalid_siret"}

    url = f"{BASE_URL}?q={siret_norm}&limite_matching_etablissements=1"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"found": False, "reason": f"http_{e.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"found": False, "reason": f"network_error: {e}"}
    except json.JSONDecodeError:
        return {"found": False, "reason": "bad_json"}

    results = payload.get("results") or []
    if not results:
        return {"found": False, "reason": "not_found"}

    entreprise = results[0]
    # On cherche precisement l'etablissement correspondant au SIRET demande
    matching = entreprise.get("matching_etablissements") or []
    etab = next((e for e in matching if e.get("siret") == siret_norm), None)
    if etab is None:
        etab = entreprise.get("siege") or {}

    etat_admin = (etab.get("etat_administratif") or "A").upper()
    actif = etat_admin == "A"

    adresse = (etab.get("adresse") or "").strip()
    code_postal = (etab.get("code_postal") or "").strip()
    ville = (etab.get("libelle_commune") or "").strip()

    # L'API renvoie une adresse complete "RUE... CP VILLE".
    # On strip le CP + ville pour que adresse_ligne1 ne contienne que la rue.
    adresse_ligne1 = adresse
    if code_postal and code_postal in adresse_ligne1:
        adresse_ligne1 = adresse_ligne1.split(code_postal, 1)[0].rstrip(" ,")
    adresse_ligne2 = (etab.get("complement_adresse") or "").strip()

    raison_sociale = (
        entreprise.get("nom_raison_sociale")
        or entreprise.get("nom_complet")
        or ""
    ).strip()

    return {
        "found": True,
        "siret": siret_norm,
        "raison_sociale": raison_sociale,
        "adresse_ligne1": adresse_ligne1,
        "adresse_ligne2": adresse_ligne2,
        "code_postal": code_postal,
        "ville": ville,
        "actif": actif,
    }
