"""Rendu du markdown produit par le modèle, et nettoyage des extraits de flux.

Le convertisseur est volontairement minimal (pas de dépendance markdown), donc
c'est du code maison qui écrit du HTML injecté dans la page : l'échappement est
la partie qui mérite un test, pas la mise en forme.
"""
from __future__ import annotations

from veille import feeds, site


def test_le_html_present_dans_le_texte_est_echappe():
    """Un digest qui contiendrait du HTML ne doit pas l'exécuter dans la page."""
    html = site.markdown_html("Un <script>alert(1)</script> dans le texte")

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_gras_code_et_liens_sont_convertis():
    html = site.markdown_html("**Gras**, `code`, et [lien](https://exemple.test/a).")

    assert "<strong>Gras</strong>" in html
    assert "<code>code</code>" in html
    assert '<a href="https://exemple.test/a"' in html
    assert 'rel="noopener"' in html


def test_une_liste_devient_une_liste():
    html = site.markdown_html("- premier\n- second")

    assert html.count("<li>") == 2
    assert "<ul>" in html


def test_un_bloc_de_code_garde_son_contenu_litteral():
    """Le mode « développer » produit des exemples de commandes : ils doivent tenir."""
    html = site.markdown_html("```\npython run_daily.py --dry-run\n```")

    assert "<pre" in html or "<code" in html
    assert "python run_daily.py --dry-run" in html


def test_un_extrait_de_flux_est_debalise_et_tronque():
    brut = "<p>Une annonce <b>importante</b> et " + "longue " * 200 + "</p>"

    propre = feeds.nettoyer_html(brut, limite=80)

    assert "<" not in propre
    assert len(propre) <= 81  # la troncature ajoute une ellipse
    assert propre.endswith("…")


def test_un_extrait_court_est_rendu_tel_quel():
    assert feeds.nettoyer_html("<p>Court et net</p>", limite=80) == "Court et net"
