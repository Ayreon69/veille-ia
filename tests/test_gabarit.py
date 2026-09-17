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
