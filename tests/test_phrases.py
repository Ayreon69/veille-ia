"""Les phrases du digest, rattachées à leur élément.

Le digest est déjà écrit en français, une phrase par élément. Ces tests protègent
le passage du markdown au texte simple : une référence arrière perdue dans un
`re.sub` remplaçait déjà le contenu d'un `code` par un caractère de contrôle, sans
que rien n'échoue — la page affichait un carré vide au milieu d'une phrase.
"""
from __future__ import annotations

from veille import site

DIGEST = """## À retenir
- **Claude Code v2.1.274** : une mise à jour majeure, sans lien dans cette section.

## Claude & Claude Code
- **Claude Code v2.1.274 : gestion mémoire** — Anthropic ajoute la variable
  `CLAUDE_CODE_MCP_STARTUP_WAIT_MS` et **corrige** la reprise de sessions, comme
  l'explique [le billet](https://exemple.test/billet). [lien](https://exemple.test/a)
- **Trop court** — bref. [lien](https://exemple.test/b)
"""


def test_la_phrase_est_rattachee_a_son_url():
    phrases = site.phrases_du_digest(DIGEST)

    assert "https://exemple.test/a" in phrases
    assert phrases["https://exemple.test/a"].startswith("Anthropic ajoute")


def test_le_markdown_est_rendu_en_texte_simple():
    phrase = site.phrases_du_digest(DIGEST)["https://exemple.test/a"]

    assert "CLAUDE_CODE_MCP_STARTUP_WAIT_MS" in phrase, "le code a disparu"
    assert "corrige" in phrase and "**" not in phrase, "le gras a mangé son contenu"
    assert "le billet" in phrase and "http" not in phrase, "le lien a mangé son texte"
    assert not [c for c in phrase if ord(c) < 32], "caractère de contrôle dans la phrase"


def test_les_puces_sans_lien_et_les_fragments_sont_ignores():
    phrases = site.phrases_du_digest(DIGEST)

    # « À retenir » est une synthèse transversale : ses puces ne portent pas de lien.
    assert len(phrases) == 1
    assert "https://exemple.test/b" not in phrases, "« bref. » n'est pas une phrase"


def test_le_point_du_jour_se_separe_du_detail():
    retenir, reste = site._section_a_retenir(DIGEST)

    assert retenir.startswith("- **Claude Code")
    assert "## " not in retenir, "le titre de section ne doit pas être repris"
    assert reste.startswith("## Claude & Claude Code")
