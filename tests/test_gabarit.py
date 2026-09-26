"""Le gabarit est assemblé depuis trois fichiers : il doit le rester entier.

Depuis le 2026-09-17, page.html, style.css et app.js vivent dans
veille/gabarit/ au lieu d'une chaîne Python. Ces tests protègent le point
faible de ce découpage : un marqueur mal remplacé produirait une page sans
style ou sans script, sans lever la moindre erreur à la construction.
"""
from __future__ import annotations

from veille import site


def test_le_gabarit_contient_le_style_et_le_script():
    g = site.gabarit()

    assert "__STYLE__" not in g and "__SCRIPT__" not in g
    assert "<style>" in g and "</style>" in g
    assert g.count("<script") >= 2  # les données, puis l'application


def test_les_marqueurs_de_contenu_survivent_a_l_assemblage():
    """__POLICES__ et __DONNEES__ sont remplis plus tard, par construire()."""
    g = site.gabarit()

    assert "__POLICES__" in g
    assert "__DONNEES__" in g


def test_le_style_et_le_script_ne_sont_pas_vides():
    g = site.gabarit()
    style = g.split("<style>")[1].split("</style>")[0]
    script = g.rsplit("<script>", 1)[1].split("</script>")[0]

    assert len(style) > 5_000, "le CSS n'a pas été inséré"
    assert len(script) > 20_000, "le JS n'a pas été inséré"


def test_le_theme_choisi_est_pose_avant_la_feuille_de_style():
    """Posé après, la page s'afficherait un instant dans l'autre thème à chaque visite."""
    g = site.gabarit()

    assert "veille-theme" in g
    assert g.index("veille-theme") < g.index("<style>")


def test_les_tendances_sont_aussi_publiees():
    """Tendances ne lit que les journées de la page : le site public y a droit.

    Le test lit la déclaration des vues publiques dans le script, et vérifie qu'elle
    ne nomme ni les signets, ni les favoris, ni la semaine.
    """
    g = site.gabarit()
    # « ? {veille:'Veille', …} » : la première ligne après le test du mode public.
    publiques = g.split("const VUES = D.public", 1)[1].split("?", 1)[1].split("\n", 1)[0]

    assert "tendances" in publiques
    for privee in ("signets", "favoris", "semaine"):
        assert privee not in publiques
