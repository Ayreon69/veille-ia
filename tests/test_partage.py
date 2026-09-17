"""Ce que la page dit d'elle-même une fois publiée : métadonnées et flux RSS.

Un lien partagé sans aperçu, un flux qui ne s'ouvre pas : rien de tout cela ne
lève d'erreur à la construction, et personne ne le voit avant de coller le lien
quelque part. D'où ces vérifications.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from veille import config, site

DONNEES = {
    "jours": [
        {
            "date": "2026-09-17",
            "items": [
                {
                    "titre": "v2.1.274",
                    "url": "https://exemple.test/a",
                    "date": "2026-09-17T00:12:02+00:00",
                    "source_nom": "Claude Code (releases)",
                    "voie": "essentiel",
                    "phrase": "Une phrase française & un esperluette.",
                },
                {
                    "titre": "Du bruit",
                    "url": "https://exemple.test/b",
                    "date": "2026-09-17T01:00:00+00:00",
                    "source_nom": "Ailleurs",
                    "voie": "bruit",
                    "extrait": "ignoré",
                },
            ],
        }
    ]
}


def test_le_flux_est_un_xml_valide():
    racine = ET.fromstring(site.flux_rss(DONNEES))

    assert racine.tag == "rss"
    assert racine.find("./channel/title").text.startswith("Veille IA")


def test_le_flux_ne_porte_que_l_essentiel():
    articles = ET.fromstring(site.flux_rss(DONNEES)).findall("./channel/item")

    assert len(articles) == 1, "un élément « bruit » s'est glissé dans le flux"
    assert articles[0].find("title").text == "v2.1.274"
    assert articles[0].find("description").text.startswith("Une phrase")
    # RFC 822 : les lecteurs RSS trient là-dessus, une date ISO n'y suffit pas.
    assert articles[0].find("pubDate").text.startswith("Thu, 17 Sep 2026")


def test_la_page_publiee_porte_ses_metadonnees():
    page = site.gabarit().replace("__URL__", config.URL_PUBLIQUE)

    assert "__URL__" not in page
    assert f'content="{config.URL_PUBLIQUE}/partage.png"' in page
    assert 'rel="icon"' in page and "data:image/svg+xml" in page, "icône non embarquée"
    assert 'type="application/rss+xml"' in page


def test_les_champs_vides_ne_partent_pas_dans_la_page():
    compact = site._compacter(
        {
            "titre": "t", "url": "u", "date": "d", "source_nom": "s", "voie": "utile",
            "analyse": "", "cible": "", "aussi": [], "titre_utilisateur": False,
            "prioritaire": True, "version": True, "poids": 1, "score": 0.0,
            "extrait": "brut", "phrase": "la phrase",
        }
    )

    assert "analyse" not in compact and "cible" not in compact and "aussi" not in compact
    assert "titre_utilisateur" not in compact and "poids" not in compact
    # True == 1 en Python : un test de valeur aurait effacé tous les drapeaux vrais.
    assert compact["prioritaire"] is True and compact["version"] is True
    assert compact["score"] == 0.0, "0 est un score, pas une absence"
    assert "extrait" not in compact, "l'extrait brut double la phrase du digest"
