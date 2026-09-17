"""Le rail « Versions publiées » ne tient qu'à un fil : le repérage des sources qui
publient des versions. Si ce repérage tombe à zéro — une source renommée, un flux
changé — la colonne se vide sans lever la moindre erreur, et personne ne le voit.
"""
from __future__ import annotations

from veille import site


def test_les_sources_de_versions_sont_reperees():
    ids = site._sources_de_versions()

    assert ids, "aucune source de versions : le rail serait vide en silence"
    assert "claude_code" in ids, "la priorité n°1 du profil doit en faire partie"


def test_seuls_les_flux_de_versions_sont_retenus():
    """Un blog ou un agrégateur n'est pas une source de versions."""
    ids = site._sources_de_versions()

    assert "hackernews" not in ids
    assert not {s for s in ids if "reddit" in s}
