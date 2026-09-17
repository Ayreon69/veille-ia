"""Les fontes sont embarquées : si un fichier manque, rien ne casse — et c'est le
problème. La page reste lisible dans la pile système, et la titraille perd Fraunces
sans qu'aucune erreur ne le signale, ni à la construction ni dans le navigateur.
Ces tests sont le seul endroit où cet oubli devient visible.
"""
from __future__ import annotations

from veille import site


def test_chaque_fonte_declaree_existe():
    manquantes = [
        nom for nom, *_ in site._FONTES if not (site.DOSSIER_ASSETS / nom).exists()
    ]
    assert not manquantes, f"fontes déclarées mais absentes de assets/ : {manquantes}"


def test_les_trois_familles_sont_embarquees():
    css = site.polices()

    for famille in ("IBM Plex Sans", "Fraunces", "IBM Plex Mono"):
        assert f"font-family:'{famille}'" in css
    assert css.count("@font-face") == len(site._FONTES)
    assert "https://" not in css, "une fonte doit être en base64, jamais en lien"


def test_le_style_appelle_les_familles_embarquees():
    """Une fonte embarquée que personne n'appelle est un poids mort."""
    style = site.gabarit().split("<style>")[1].split("</style>")[0]

    assert "--titre:Fraunces" in style
    assert "--mono:'IBM Plex Mono'" in style
