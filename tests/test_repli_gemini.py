"""Un modèle Gemini saturé ne doit plus faire tomber la veille du jour.

Du 18 au 24/09/2026, cinq exécutions sur neuf ont échoué sur un 503 du seul modèle
principal, et l'hebdo de la semaine 38 n'a jamais été écrit. Le repli essaie donc
d'autres modèles — mais seulement pour les erreurs qu'un autre modèle pourrait ne
pas avoir. Une clé refusée l'est partout : insister ne ferait que retarder l'échec.
"""
from __future__ import annotations

import pytest

from veille import config, summarize


class Reponse:
    """Le strict nécessaire d'une réponse httpx pour _appeler_gemini."""

    def __init__(self, code: int, texte: str = ""):
        self.status_code = code
        self.text = texte
        self._texte = texte

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": self._texte}]}}]}

    def raise_for_status(self):
        pass


@pytest.fixture(autouse=True)
def sans_attente(monkeypatch):
    """Ni attente entre deux tentatives, ni vraie clé, ni vrais modèles."""
    monkeypatch.setattr(summarize.time, "sleep", lambda s: None)
    monkeypatch.setenv("GEMINI_API_KEY", "cle-de-test")
    monkeypatch.setattr(config, "MODELE_GEMINI", "principal")
    monkeypatch.setattr(config, "MODELES_GEMINI_SECOURS", ["secours-1", "secours-2"])


def test_un_principal_sature_passe_la_main_au_secours(monkeypatch):
    appels = []

    def post(url, **_):
        appels.append(url)
        return Reponse(503) if "principal" in url else Reponse(200, "digest du secours")

    monkeypatch.setattr(summarize.httpx, "post", post)

    assert summarize._resumer_gemini("prompt") == "digest du secours"
    # Le principal garde ses quatre tentatives avant qu'on renonce à lui.
    assert sum("principal" in u for u in appels) == 4
    assert "secours-1" in appels[-1]


def test_un_modele_retire_n_empeche_pas_le_suivant(monkeypatch):
    """Un identifiant de repli qui n'existe plus (404) ne doit pas tout arrêter."""
    def post(url, **_):
        if "principal" in url:
            return Reponse(503)
        if "secours-1" in url:
            return Reponse(404)
        return Reponse(200, "digest")

    monkeypatch.setattr(summarize.httpx, "post", post)

    assert summarize._resumer_gemini("prompt") == "digest"


def test_une_cle_refusee_n_essaie_pas_les_autres_modeles(monkeypatch):
    appels = []

    def post(url, **_):
        appels.append(url)
        return Reponse(401, "API key not valid")

    monkeypatch.setattr(summarize.httpx, "post", post)

    with pytest.raises(RuntimeError, match="refusée"):
        summarize._resumer_gemini("prompt")
    assert len(appels) == 1


def test_quand_tout_est_indisponible_le_message_nomme_les_modeles(monkeypatch):
    monkeypatch.setattr(summarize.httpx, "post", lambda url, **_: Reponse(503))

    with pytest.raises(RuntimeError) as erreur:
        summarize._resumer_gemini("prompt")
    for modele in ("principal", "secours-1", "secours-2"):
        assert modele in str(erreur.value)
    assert "rien n'est perdu" in str(erreur.value)
