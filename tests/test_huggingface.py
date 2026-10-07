"""Poids ouverts et papiers de recherche, lus sur l'API publique de Hugging Face.

Ajoutés le 06/10/2026 : Qwen, DeepSeek ou Meta n'arrivaient que de seconde main, et la
recherche presque pas. Ces tests ne touchent pas au réseau.
"""
from __future__ import annotations

from veille import huggingface, summarize


class Reponse:
    status_code = 200

    def __init__(self, donnees):
        self._donnees = donnees

    def json(self):
        return self._donnees

    def raise_for_status(self):
        pass


def test_les_variantes_quantifiees_sont_ecartees(monkeypatch):
    modeles = [
        {"id": "deepseek-ai/DeepSeek-V4.1-Flash", "createdAt": "2026-10-05T08:00:00.000Z",
         "pipeline_tag": "text-generation", "likes": 120, "downloads": 900},
        {"id": "deepseek-ai/DeepSeek-V4.1-Flash-GGUF", "createdAt": "2026-10-05T09:00:00.000Z"},
        {"id": "deepseek-ai/DeepSeek-V4.1-Flash-NVFP4", "createdAt": "2026-10-05T09:00:00.000Z"},
    ]
    monkeypatch.setattr(huggingface, "_http_get", lambda url, params=None: Reponse(modeles))

    items = huggingface.lire_modeles({"url": "u", "params": {"organisations": ["deepseek-ai"]}})

    assert [it["url"] for it in items] == ["https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash"]
    assert items[0]["titre"] == "deepseek-ai publie DeepSeek-V4.1-Flash sur Hugging Face"
    assert "text-generation" in items[0]["extrait"]


def test_seuls_les_papiers_les_plus_votes_de_la_veille_remontent(monkeypatch):
    demandes = []

    def get(url, params=None):
        demandes.append(params)
        return Reponse([
            {"paper": {"id": "2610.1", "title": "Peu voté", "upvotes": 3, "summary": "x"}},
            {"paper": {"id": "2610.2", "title": "Très voté", "upvotes": 40,
                       "summary": "Un   résumé\n sur deux lignes."}},
        ])

    monkeypatch.setattr(huggingface, "_http_get", get)
    items = huggingface.lire_papiers({"url": "u", "params": {"min_votes": 15}})

    assert [it["titre"] for it in items] == ["Très voté"]
    assert items[0]["url"] == "https://huggingface.co/papers/2610.2"
    assert items[0]["extrait"] == "40 votes sur Hugging Face Papers. Un résumé sur deux lignes."
    assert "date" in demandes[0]  # la veille, dont les votes sont acquis


def test_la_grille_n_a_plus_de_plancher_claude():
    """Révisée le 06/10 : Claude prenait 90 essentiels sur 116 en huit jours."""
    for mode in ("quotidien", "tri"):
        consignes = summarize._CONSIGNES[mode]
        assert "0,80 au minimum" not in consignes
        assert "bonus" in consignes and "{GRILLE}" not in consignes


def test_un_essentiel_sans_date_ne_casse_pas_le_flux_rss():
    """Le 07/10, un papier archivé sans date a fait tomber la construction du site public."""
    from veille import site

    donnees = {"jours": [{"date": "2026-10-07", "items": [
        {"titre": "Papier", "url": "https://huggingface.co/papers/1", "date": None,
         "voie": "essentiel", "source_nom": "Hugging Face Papers"},
    ]}]}

    flux = site.flux_rss(donnees)

    assert "<pubDate>Wed, 07 Oct 2026 00:00:00 +0200</pubDate>" in flux
