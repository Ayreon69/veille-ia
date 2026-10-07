"""
Deux angles morts couverts par l'API publique de Hugging Face, sans clé.

- `hf_modeles` : les poids publiés par les labos eux-mêmes (Qwen, DeepSeek, Meta,
  Mistral, Black Forest Labs…). Beaucoup n'ont ni blog ni flux — DeepSeek, Moonshot,
  Zhipu — et une sortie de poids ouverts n'arrivait jusqu'ici que par r/LocalLLaMA,
  de seconde main et sous un titre d'utilisateur.
- `hf_papiers` : les papiers de la veille les plus votés sur Hugging Face Papers. La
  veille seulement : les votes du jour ne sont pas encore arrivés au moment du run.
"""
import re
from datetime import UTC, datetime, timedelta

from .feeds import _http_get

# Variantes techniques d'un même modèle : la sortie d'origine suffit.
_DERIVES = re.compile(r"(gguf|awq|gptq|fp8|nvfp4|mlx|int4|int8|bnb|onnx)", re.I)


def _date(valeur: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((valeur or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def lire_modeles(source: dict) -> list[dict]:
    """Derniers modèles publiés par chaque organisation de `params.organisations`."""
    items = []
    for org in source.get("params", {}).get("organisations", []):
        reponse = _http_get(
            source["url"],
            params={"author": org, "sort": "createdAt", "direction": -1, "limit": 10},
        )
        reponse.raise_for_status()
        for modele in reponse.json():
            ident = modele.get("id", "")
            if not ident or _DERIVES.search(ident):
                continue
            tache = modele.get("pipeline_tag") or "modèle"
            items.append({
                "titre": f"{org} publie {ident.split('/', 1)[-1]} sur Hugging Face",
                "url": f"https://huggingface.co/{ident}",
                "date": _date(modele.get("createdAt")),
                "extrait": (
                    f"Nouveaux poids publiés par {org} ({tache}). "
                    f"{modele.get('likes', 0)} j'aime, "
                    f"{modele.get('downloads', 0)} téléchargements à la collecte."
                ),
            })
    return items


def lire_papiers(source: dict) -> list[dict]:
    """Papiers de la veille sur Hugging Face Papers, au-dessus de `params.min_votes`."""
    params = source.get("params", {})
    veille = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    reponse = _http_get(source["url"], params={"date": veille, "limit": 100})
    reponse.raise_for_status()

    papiers = sorted(
        (p.get("paper") or {} for p in reponse.json()),
        key=lambda p: p.get("upvotes", 0),
        reverse=True,
    )
    items = []
    for papier in papiers[: params.get("max_entrees", 8)]:
        if papier.get("upvotes", 0) < params.get("min_votes", 15) or not papier.get("id"):
            continue
        resume = " ".join((papier.get("summary") or "").split())
        limite = source.get("extrait_max", 800)
        if len(resume) > limite:
            resume = resume[:limite].rsplit(" ", 1)[0] + "…"
        items.append({
            "titre": papier.get("title", "").strip(),
            "url": f"https://huggingface.co/papers/{papier['id']}",
            # Sa date de présentation sur Hugging Face Papers (la veille). Archivé sans
            # date, il a fait tomber la construction du site public le 07/10.
            "date": _date(papier.get("submittedOnDailyAt") or papier.get("publishedAt")),
            "extrait": f"{papier.get('upvotes', 0)} votes sur Hugging Face Papers. {resume}",
        })
    return items
