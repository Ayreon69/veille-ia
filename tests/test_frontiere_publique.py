"""La garantie la plus importante du projet : ce qui est personnel ne sort pas.

Le site public et le site personnel sortent du même générateur, distingués par un
seul drapeau (`site._preparer(public=True)`). Sans ce test, une régression y
publierait les signets, les favoris, les développements, les digests hebdomadaires
ou le profil personnel — sans que rien ne prévienne, et sur une page en ligne.

Chaque test dit donc ce qui ne doit PAS apparaître, jamais l'inverse.
"""
from __future__ import annotations

import pytest

from veille import config, site

PHRASE_SIGNET = "signet-que-personne-ne-doit-voir"
PHRASE_FAVORI = "favori-que-personne-ne-doit-voir"
PHRASE_DEV = "developpement-que-personne-ne-doit-voir"
PHRASE_SEMAINE = "digest-hebdo-que-personne-ne-doit-voir"


@pytest.fixture
def jours() -> list[dict]:
    """Une journée contenant un item normal et un signet personnel."""
    return [
        {
            "date": "2026-09-17",
            "items": [
                {
                    "url": "https://exemple.test/article",
                    "titre": "Sortie d'un modèle",
                    "score": 0.9,
                    "categorie": "modeles",
                },
                {
                    "url": "https://x.test/statut/1",
                    "titre": PHRASE_SIGNET,
                    "score": 0.8,
                    "categorie": "signets",
                },
            ],
            "digests": [{"heure": "05h00", "corps": "Rien de notable."}],
        }
    ]


@pytest.fixture(autouse=True)
def sans_vault(monkeypatch):
    """Coupe les trois lectures du vault, remplacées par du contenu reconnaissable.

    Le test doit pouvoir tourner dans un dépôt sans vault (c'est le cas en CI) tout
    en vérifiant que le mode public ignore ces sources, non qu'elles sont vides.
    """
    monkeypatch.setattr(
        site.favoris, "charger",
        lambda: {"favoris": [{"url": "https://exemple.test/favori", "titre": PHRASE_FAVORI, "score": 0.7}]},
    )
    monkeypatch.setattr(
        site.developpements, "charger",
        lambda: {"https://exemple.test/article": {"corps": PHRASE_DEV, "genere": "2026-09-17"}},
    )
    monkeypatch.setattr(
        site, "charger_semaines",
        lambda *a, **k: [{"identifiant": "2026-W38", "libelle": "semaine", "html": PHRASE_SEMAINE}],
    )


def test_le_mode_public_retire_signets_favoris_developpements_et_semaines(jours):
    public = site._preparer(jours, public=True)

    urls = [it["url"] for j in public["jours"] for it in j["items"]]
    assert "https://x.test/statut/1" not in urls
    assert public["favoris"] == []
    assert public["developpements"] == {}
    assert public["semaines"] == []


def test_le_mode_personnel_les_conserve(jours):
    """Miroir du test précédent : sans le drapeau, rien n'est retiré.

    Sans ce contrôle, un générateur qui expurgerait tout passerait le test ci-dessus.
    """
    perso = site._preparer(jours, public=False)

    urls = [it["url"] for j in perso["jours"] for it in j["items"]]
    assert "https://x.test/statut/1" in urls
    assert perso["favoris"] and perso["favoris"][0]["titre"] == PHRASE_FAVORI
    assert perso["developpements"]
    assert perso["semaines"]


def test_le_profil_embarque_est_le_profil_public(jours):
    """Le prompt voyage dans la page publique : ce doit être celui du lectorat."""
    public = site._preparer(jours, public=True)

    assert public["profil"] == config.PROFIL_PUBLIC
    assert config.PROFIL not in public["profil"]
    # Le site personnel n'embarque aucun prompt : il n'en a pas besoin.
    assert site._preparer(jours, public=False)["profil"] == ""


def test_aucune_phrase_personnelle_dans_la_page_publique(jours, monkeypatch, tmp_path):
    """Le contrôle de bout en bout, sur le HTML réellement écrit.

    Les tests ci-dessus portent sur la structure intermédiaire ; celui-ci lit le
    fichier produit, seul artefact qui part en ligne.
    """
    monkeypatch.setattr(site, "charger_jours", lambda *a, **k: jours)
    monkeypatch.setattr(site, "DOSSIER_PUBLIC", tmp_path)

    chemin = site.construire(public=True)
    html = chemin.read_text(encoding="utf-8")

    for phrase in (PHRASE_SIGNET, PHRASE_FAVORI, PHRASE_DEV, PHRASE_SEMAINE):
        assert phrase not in html
    # Le profil personnel décrit une personne : il ne doit apparaître sous aucune forme.
    assert "migration SAS" not in html
    assert config.PROFIL_PUBLIC.splitlines()[0] in html
