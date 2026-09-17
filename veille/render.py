"""
Génération des notes markdown destinées au vault Obsidian.
"""
import re
from datetime import date

from jinja2 import Template

_MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]

# Le frontmatter permet à Dataview de requêter la veille dans le temps.
_GABARIT_QUOTIDIEN = Template(
    """---
tags: [veille-ia, quotidien]
date: {{ jour.isoformat() }}
items: {{ nb_items }}
sources_ok: {{ nb_sources_ok }}
---

# Veille IA — {{ jour.day }} {{ mois }} {{ jour.year }}

{{ corps }}
{% if echecs %}
---

> [!warning]- Sources en échec ({{ echecs | length }})
{%- for e in echecs %}
> - **{{ e.source }}** — {{ e.erreur }}
{%- endfor %}
{% endif %}""",
    trim_blocks=False,
    lstrip_blocks=False,
)

_GABARIT_HEBDO = Template(
    """---
tags: [veille-ia, digest]
semaine: {{ semaine }}
debut: {{ debut.isoformat() }}
fin: {{ fin.isoformat() }}
items: {{ nb_items }}
---

# Digest IA — semaine {{ numero_semaine }} ({{ debut.day }} au {{ fin.day }} {{ mois_fin }} {{ fin.year }})

{{ corps }}

---

## Notes quotidiennes de la semaine
{% for note in notes_quotidiennes %}
- [[{{ note }}]]
{%- endfor %}
{% if not notes_quotidiennes %}
_Aucune note quotidienne trouvée pour cette semaine._
{% endif %}""",
    trim_blocks=False,
    lstrip_blocks=False,
)


def rendre_quotidien(
    jour: date, corps: str, nb_items: int, nb_sources_ok: int, echecs: list[dict]
) -> str:
    """Assemble la note quotidienne complète."""
    return _GABARIT_QUOTIDIEN.render(
        jour=jour,
        mois=_MOIS[jour.month - 1],
        corps=corps.strip(),
        nb_items=nb_items,
        nb_sources_ok=nb_sources_ok,
        echecs=echecs,
    )


def rendre_mise_a_jour(heure: str, corps: str, nb_items: int) -> str:
    """Rend un bloc à ajouter à une note quotidienne déjà écrite.

    Les titres du digest sont rétrogradés d'un niveau (## -> ###) pour s'imbriquer
    sous le titre de la mise à jour sans casser le plan du document.
    """
    corps_imbrique = re.sub(r"^## ", "### ", corps.strip(), flags=re.MULTILINE)
    return (
        f"---\n\n## Mise à jour de {heure}\n\n"
        f"_{nb_items} élément{'s' if nb_items > 1 else ''} "
        f"arrivé{'s' if nb_items > 1 else ''} depuis le digest précédent._\n\n"
        f"{corps_imbrique}\n"
    )


_GABARIT_SIGNETS = Template(
    """---
tags: [veille-ia, signets]
date: {{ jour.isoformat() }}
signets: {{ nb_items }}
---

# Signets X — {{ jour.day }} {{ mois }} {{ jour.year }}

{{ corps }}
""",
    trim_blocks=False,
    lstrip_blocks=False,
)


def rendre_signets(jour: date, corps: str, nb_items: int) -> str:
    """Assemble la note de signets du jour."""
    return _GABARIT_SIGNETS.render(
        jour=jour, mois=_MOIS[jour.month - 1], corps=corps.strip(), nb_items=nb_items
    )


def rendre_ajout_signets(heure: str, corps: str, nb_items: int) -> str:
    """Bloc à ajouter à une note de signets déjà écrite."""
    return (
        f"---\n\n## Relevé de {heure}\n\n"
        f"_{nb_items} nouveau{'x' if nb_items > 1 else ''} signet"
        f"{'s' if nb_items > 1 else ''}._\n\n{corps.strip()}\n"
    )


def rendre_hebdo(
    debut: date, fin: date, corps: str, nb_items: int, notes_quotidiennes: list[str]
) -> str:
    """Assemble le digest hebdomadaire.

    Le digest lie les notes quotidiennes en [[...]] au lieu de recopier leur
    contenu : c'est ce qui rend la veille navigable dans la durée.
    """
    an, numero, _ = fin.isocalendar()
    return _GABARIT_HEBDO.render(
        semaine=f"{an}-W{numero:02d}",
        numero_semaine=numero,
        debut=debut,
        fin=fin,
        mois_fin=_MOIS[fin.month - 1],
        corps=corps.strip(),
        nb_items=nb_items,
        notes_quotidiennes=notes_quotidiennes,
    )


def nom_note_quotidienne(jour: date) -> str:
    return jour.isoformat()


def nom_note_hebdo(fin: date) -> str:
    # Année ISO et non civile : le dimanche 3 janvier 2027 appartient à la semaine 53
    # de 2026. `fin.year` donnerait « 2027-W53 », une semaine qui n'existe pas.
    an, numero, _ = fin.isocalendar()
    return f"{an}-W{numero:02d}"
