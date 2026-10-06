"""Le point du jour lu par une voix Gemini : ce qui est dit, et sous quelle forme.

Ajouté le 06/10/2026. Les appels au modèle de voix ne sont pas testés ici (réseau) ;
on vérifie ce qui lui est envoyé et ce qu'on fait de sa réponse.
"""
from __future__ import annotations

import io
import wave

from veille import voix

JOUR = {
    "date": "2026-10-01",
    "digests": [{"corps": (
        "## À retenir\n"
        "- **Sortie de Claude Code v2.1.291** — Corrige une régression. [lien](https://github.com/x)\n"
        "- **Mods dans `Claude Code`** — Anthropic formalise les mods.\n"
        "\n## Claude & Claude Code\n- **Autre** — Pas lu. [lien](https://a)\n"
    )}],
}


def test_le_texte_lu_est_sans_markdown_ni_lien():
    texte = voix.texte_du_point(JOUR)

    assert texte.startswith("Le point du 1er octobre.")
    assert "Sortie de Claude Code v2.1.291. Corrige une régression." in texte
    assert "Mods dans Claude Code. Anthropic formalise les mods." in texte
    for absent in ("**", "`", "github", "lien", "Pas lu"):
        assert absent not in texte


def test_un_jour_sans_point_ne_produit_rien():
    assert voix.texte_du_point({"date": "2026-10-01", "digests": [{"corps": "rien"}]}) == ""


def test_le_pcm_brut_recoit_un_en_tete_wav_et_le_wav_reste_tel_quel():
    pcm = b"\x00\x01" * 2400
    wav = voix._en_wav(pcm, "audio/L16;codec=pcm;rate=24000")
    with wave.open(io.BytesIO(wav)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (24000, 1, 2400)
    assert voix._en_wav(wav, "audio/wav") == wav
