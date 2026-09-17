"""
Déduplication persistante des articles déjà traités.

Indispensable : les agrégateurs (smol.ai, TLDR, Hacker News) relaient les mêmes
annonces que les blogs de labs. Sans cet étage, le digest se répète.
"""
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from . import config

_PARAMS_PARASITES = re.compile(r"^(utm_|ref_?$|ref_src|fbclid|gclid|mc_cid|mc_eid|source$)")


def normaliser_url(url: str) -> str:
    """Normalise une URL pour la comparaison.

    Retire le fragment, les paramètres de tracking, le slash final et le www,
    et force le schéma en https : la même annonce circule sous des URLs variées.
    """
    try:
        p = urlparse(url.strip())
    except ValueError:
        return url.strip().lower()

    netloc = p.netloc.lower().removeprefix("www.")
    chemin = p.path.rstrip("/") or "/"

    query = urlencode(
        [(k, v) for k, v in parse_qsl(p.query) if not _PARAMS_PARASITES.match(k)]
    )

    return urlunparse(("https", netloc, chemin, "", query, ""))


def cle_item(item: dict) -> str:
    """Empreinte stable d'un item, basée sur son URL normalisée."""
    return hashlib.sha1(normaliser_url(item["url"]).encode("utf-8")).hexdigest()


def charger_seen() -> dict[str, str]:
    """Charge l'état des URLs déjà vues ({empreinte: date ISO})."""
    if not config.FICHIER_SEEN.exists():
        return {}
    try:
        return json.loads(config.FICHIER_SEEN.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Un état corrompu ne doit pas bloquer le run : on repart à vide.
        return {}


def enregistrer_seen(seen: dict[str, str]) -> None:
    """Écrit l'état sur disque après purge des entrées trop anciennes."""
    limite = datetime.now(UTC) - timedelta(days=config.RETENTION_SEEN_JOURS)
    seen = {
        cle: date
        for cle, date in seen.items()
        if _date_ou_none(date) is None or _date_ou_none(date) > limite
    }

    config.DOSSIER_STATE.mkdir(parents=True, exist_ok=True)
    config.FICHIER_SEEN.write_text(
        json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _date_ou_none(valeur: str) -> datetime | None:
    try:
        return datetime.fromisoformat(valeur)
    except (ValueError, TypeError):
        return None


def filtrer_nouveaux(items: list[dict], seen: dict[str, str]) -> list[dict]:
    """Écarte les items déjà vus, ainsi que les doublons internes au lot."""
    maintenant = datetime.now(UTC).isoformat()
    nouveaux = []
    vus_ce_run = set()

    for item in items:
        cle = cle_item(item)
        if cle in seen or cle in vus_ce_run:
            continue
        vus_ce_run.add(cle)
        seen[cle] = maintenant
        nouveaux.append(item)

    return nouveaux
