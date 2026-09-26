"""Posts X sans session X, et les réglages de flux ajoutés avec eux.

Ajoutés le 26/09/2026 : l'équipe Claude Code publie sur X des choses qui n'existent nulle
part ailleurs. Deux voies — le flux public follow-builders, et l'API officielle avec un
jeton d'application — sans jamais toucher à un navigateur ni à un cookie.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from veille import config, feeds, reseaux


class Reponse:
    def __init__(self, code: int = 200, donnees=None, contenu: bytes = b""):
        self.status_code = code
        self._donnees = donnees
        self.content = contenu
        self.text = contenu.decode("utf-8", "replace")

    def json(self):
        return self._donnees

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _flux(*comptes):
    return {"x": [
        {"handle": h, "name": h.title(), "bio": "Claude Code @anthropicai", "tweets": tweets}
        for h, tweets in comptes
    ]}


def _post(n: int, texte: str) -> dict:
    return {"url": f"https://x.com/a/status/{n}", "text": texte,
            "createdAt": "2026-09-25T20:04:18.000Z"}


LONG = "What is effort really? When do you change it and why not just use max effort?"


def test_follow_builders_lit_l_historique_et_filtre(monkeypatch):
    """Trois versions du fichier : un post présent dans deux d'entre elles ne sort qu'une fois,
    les posts sans contenu et les comptes exclus disparaissent."""
    versions = {
        "sha1": _flux(("trq212", [_post(1, LONG), _post(2, "o no :( https://t.co/abc")])),
        "sha2": _flux(("trq212", [_post(1, LONG)]), ("garrytan", [_post(3, LONG)])),
    }

    def get(url, params=None):
        if "api.github.com" in url:
            return Reponse(donnees=[{"sha": s} for s in versions])
        return Reponse(donnees=versions[url.split("/")[-2]])

    monkeypatch.setattr(reseaux, "_http_get", get)
    items = reseaux.lire_follow_builders({
        "url": "https://raw.githubusercontent.com/d/f/main/feed-x.json",
        "params": {"depot": "d/f", "exclure": ["GarryTan"]},
    })

    assert [it["url"] for it in items] == ["https://x.com/a/status/1"]
    assert items[0]["titre"].startswith("@trq212 : What is effort")
    assert items[0]["date"] == datetime(2026, 9, 25, 20, 4, 18, tzinfo=UTC)
    assert "Claude Code @anthropicai" in items[0]["extrait"]


def test_follow_builders_se_contente_du_fichier_courant_sans_l_api_github(monkeypatch):
    def get(url, params=None):
        if "api.github.com" in url:
            return Reponse(403)
        return Reponse(donnees=_flux(("bcherny", [_post(7, LONG + " &amp; more")])))

    monkeypatch.setattr(reseaux, "_http_get", get)
    items = reseaux.lire_follow_builders({"url": "https://exemple/feed-x.json", "params": {}})

    assert len(items) == 1
    assert "& more" in items[0]["extrait"]  # entités décodées


def test_x_api_demande_la_fenetre_et_jamais_plus_de_sept_jours(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "jeton")
    requetes = []

    def get(url, params=None, headers=None, timeout=None):
        requetes.append(params)
        assert headers["Authorization"] == "Bearer jeton"
        return Reponse(donnees={"data": [{
            "id": "42", "text": "court", "created_at": "2026-09-25T10:00:00.000Z",
            "note_tweet": {"text": LONG}, "public_metrics": {"like_count": 12},
        }]})

    monkeypatch.setattr(reseaux.httpx, "get", get)
    items = reseaux.lire_x_api({
        "url": "https://api.x.com/2/tweets/search/recent",
        "_depuis": datetime.now(UTC) - timedelta(days=30),
        "params": {"comptes": ["lydiahallie"]},
    })

    assert requetes[0]["query"] == "from:lydiahallie -is:retweet -is:reply"
    debut = datetime.strptime(requetes[0]["start_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert datetime.now(UTC) - debut < timedelta(days=7)
    # Le post long (note_tweet) l'emporte sur le texte tronqué.
    assert items[0]["url"] == "https://x.com/lydiahallie/status/42"
    assert LONG in items[0]["extrait"]


def test_x_api_sans_credit_le_dit(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "jeton")
    monkeypatch.setattr(reseaux.httpx, "get", lambda *a, **k: Reponse(402))
    with pytest.raises(RuntimeError, match="crédits"):
        reseaux.lire_x_api({"url": "u", "params": {"comptes": ["trq212"]}})


def test_une_source_payante_dort_sans_son_secret(monkeypatch, tmp_path):
    fichier = tmp_path / "sources.yaml"
    fichier.write_text(json.dumps([
        {"id": "libre", "nom": "L", "type": "rss", "url": "u", "categorie": "x"},
        {"id": "payante", "nom": "P", "type": "x_api", "url": "u", "categorie": "x",
         "requiert_env": "X_BEARER_TOKEN"},
    ]), encoding="utf-8")
    monkeypatch.setattr(config, "SOURCES_YAML", fichier)

    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    assert [s["id"] for s in config.charger_sources()] == ["libre"]

    monkeypatch.setenv("X_BEARER_TOKEN", "jeton")
    assert [s["id"] for s in config.charger_sources()] == ["libre", "payante"]


RSS = b"""<?xml version="1.0"?><rss version="2.0"
 xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>Codex CLI Release: 0.157.1</title><link>https://e/1</link>
 <description>0.157.1</description></item>
<item><title>Codex CLI Release: 0.157.0</title><link>https://e/2</link>
 <description>0.157.0</description>
 <content:encoded>&lt;ul&gt;&lt;li&gt;Plan mode now streams&lt;/li&gt;&lt;/ul&gt;</content:encoded></item>
<item><title>ChatGPT for iOS</title><link>https://e/3</link></item>
<item><title>GPT-6 Sol in Codex</title><link>https://e/4</link></item>
</channel></rss>"""


def test_lire_rss_filtre_les_titres_et_prefere_le_contenu_complet(monkeypatch):
    monkeypatch.setattr(feeds, "_http_get", lambda url: Reponse(contenu=RSS))
    items = feeds.lire_rss({"url": "u", "params": {
        "exclure_titre": r"ChatGPT for (iOS|Android)|Release: \d+\.\d+\.[1-9]",
    }})

    assert [it["url"] for it in items] == ["https://e/2", "https://e/4"]
    assert items[0]["extrait"] == "Plan mode now streams"


def test_lire_rss_s_arrete_aux_premieres_entrees(monkeypatch):
    monkeypatch.setattr(feeds, "_http_get", lambda url: Reponse(contenu=RSS))
    items = feeds.lire_rss({"url": "u", "params": {"max_entrees": 2}})
    assert [it["url"] for it in items] == ["https://e/1", "https://e/2"]
