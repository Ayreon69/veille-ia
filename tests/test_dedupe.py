"""Déduplication : la mémoire qui évite de republier le même article chaque jour."""
from __future__ import annotations

from veille import dedupe


def test_les_parametres_de_suivi_ne_font_pas_deux_articles():
    """Une même URL partagée avec des paramètres de campagne reste une seule URL."""
    nu = "https://exemple.test/article"
    suivi = "https://exemple.test/article?utm_source=newsletter&utm_medium=email"

    assert dedupe.normaliser_url(suivi) == dedupe.normaliser_url(nu)


def test_un_parametre_utile_est_conserve():
    """Tout retirer casserait les sources qui identifient leur contenu par paramètre."""
    avec_id = "https://exemple.test/voir?id=42"

    assert "id=42" in dedupe.normaliser_url(avec_id)


def test_un_item_deja_vu_est_ecarte():
    items = [
        {"url": "https://exemple.test/a", "titre": "Déjà lu"},
        {"url": "https://exemple.test/b", "titre": "Nouveau"},
    ]
    seen = {dedupe.cle_item(items[0]): "2026-09-16T08:00:00"}

    nouveaux = dedupe.filtrer_nouveaux(items, seen)

    assert [it["titre"] for it in nouveaux] == ["Nouveau"]


def test_la_meme_url_a_deux_adresses_ne_passe_qu_une_fois():
    """Deux formes de la même URL dans un seul lot : une seule doit ressortir."""
    items = [
        {"url": "https://exemple.test/a", "titre": "Première forme"},
        {"url": "https://exemple.test/a?utm_source=x", "titre": "Seconde forme"},
    ]

    nouveaux = dedupe.filtrer_nouveaux(items, {})

    assert len(nouveaux) == 1
