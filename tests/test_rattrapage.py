"""Une exécution manquée ne doit plus rien coûter de définitif.

Deux trous sont apparus en septembre 2026, tous deux silencieux :

- l'hebdo n'avait qu'une tentative, le lundi. Tombée sur un 503, la semaine 38 n'a
  jamais été écrite. Il est désormais retenté chaque jour tant que sa note manque ;
- la collecte portait sur 36 heures fixes. Deux exécutions ratées d'affilée, et les
  articles du premier jour sortaient de la fenêtre sans que rien ne le signale.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta

import pytest

import run_daily
import run_weekly
from veille import config

# --------------------------------------------------------------------------- #
# L'hebdo rattrapé
# --------------------------------------------------------------------------- #


@pytest.fixture
def semaine(monkeypatch, tmp_path):
    """Un samedi 26/09/2026 : la dernière semaine complète est la 38."""
    monkeypatch.setattr(run_weekly.config, "DOSSIER_DIGESTS", tmp_path)
    monkeypatch.setattr(run_weekly.config, "aujourdhui", lambda: date(2026, 9, 26))
    monkeypatch.setattr(sys, "argv", ["run_weekly.py", "--si-absent"])
    return tmp_path


def test_une_semaine_deja_ecrite_ne_rappelle_pas_le_modele(monkeypatch, semaine):
    (semaine / "2026-W38.md").write_text("déjà écrite", encoding="utf-8")
    monkeypatch.setattr(
        run_weekly.summarize, "resumer", lambda *a, **k: pytest.fail("le modèle a été appelé")
    )

    assert run_weekly.main() == 0


def test_une_semaine_manquante_est_ecrite(monkeypatch, semaine):
    ecrites = []
    monkeypatch.setattr(run_weekly.vault, "notes_quotidiennes_entre", lambda d, f: ["2026-09-14"])
    monkeypatch.setattr(run_weekly.vault, "lire_notes_quotidiennes", lambda noms: "notes")
    monkeypatch.setattr(run_weekly.vault, "verifier_vault", lambda: None)
    monkeypatch.setattr(run_weekly.vault, "ecrire_hebdo", lambda nom, note: ecrites.append(nom) or semaine / nom)
    monkeypatch.setattr(run_weekly.summarize, "resumer", lambda *a, **k: "## L'essentiel\n\n- un fait")

    assert run_weekly.main() == 0
    assert ecrites == ["2026-W38"]


# --------------------------------------------------------------------------- #
# La fenêtre de collecte
# --------------------------------------------------------------------------- #


def _derniere_reussite(monkeypatch, il_y_a: timedelta | None):
    jours = [] if il_y_a is None else [{"maj": (datetime.now(config.FUSEAU) - il_y_a).isoformat()}]
    monkeypatch.setattr(run_daily.site, "charger_jours", lambda n: jours)


def test_la_fenetre_remonte_jusqu_a_la_derniere_reussite(monkeypatch):
    """Deux runs manqués : 72 h depuis la dernière réussite, plus la marge."""
    _derniere_reussite(monkeypatch, timedelta(hours=72))
    assert run_daily._fenetre_auto() == "84h"


def test_la_fenetre_ne_descend_pas_sous_36_heures(monkeypatch):
    """Un second passage le même jour garde la marge d'un run retardé par GitHub."""
    _derniere_reussite(monkeypatch, timedelta(hours=2))
    assert run_daily._fenetre_auto() == "36h"


def test_la_fenetre_est_plafonnee_a_une_semaine(monkeypatch):
    """Après un mois d'arrêt, on ne rapatrie pas un mois d'articles d'un coup."""
    _derniere_reussite(monkeypatch, timedelta(days=30))
    assert run_daily._fenetre_auto() == "168h"


def test_sans_archive_la_fenetre_reste_celle_d_avant(monkeypatch):
    _derniere_reussite(monkeypatch, None)
    assert run_daily._fenetre_auto() == "36h"
