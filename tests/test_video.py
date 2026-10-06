"""Une vidéo YouTube se développe à partir de la vidéo, pas de sa page.

Le 06/10, « How to use Opus 5.5 and Sonnet 5.5 » (chaîne @claude) donnait « le texte de
la page n'a pas pu être récupéré » : la page d'une vidéo ne contient rien de ce qui s'y
dit. Gemini, lui, regarde une vidéo YouTube publique à partir de son URL.
"""
from __future__ import annotations

import pytest

from veille import config, summarize


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=_f_rtbW_uFM",
    "https://www.youtube.com/shorts/iFHsEHP437U",
    "https://youtu.be/iFHsEHP437U",
])
def test_les_videos_sont_reconnues(url):
    assert summarize.video_youtube(url) == url


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/@claude",
    "https://www.anthropic.com/news/claude-opus",
    "",
])
def test_le_reste_ne_l_est_pas(url):
    assert summarize.video_youtube(url) is None


def test_developper_joint_la_video_en_basse_resolution(monkeypatch):
    monkeypatch.setattr(config, "BACKEND", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "cle-de-test")
    envoye = {}

    class Reponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "## En bref\nok"}]}}]}

    def post(url, json=None, **_):
        envoye.update(json)
        return Reponse()

    monkeypatch.setattr(summarize.httpx, "post", post)
    item = {"titre": "How to use Opus 5.5", "url": "https://www.youtube.com/shorts/iFHsEHP437U"}

    assert summarize.developper(item, "") == "## En bref\nok"
    parties = envoye["contents"][0]["parts"]
    assert parties[0] == {"file_data": {"file_uri": item["url"]}}
    assert "vidéo elle-même" in parties[1]["text"]
    assert envoye["generationConfig"]["mediaResolution"] == "MEDIA_RESOLUTION_LOW"
