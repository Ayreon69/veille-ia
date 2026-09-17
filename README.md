# Veille IA

Un système de veille sur l'actualité de l'IA qui tourne seul dans le cloud : il collecte
une trentaine de sources, note chaque élément contre un profil de pertinence explicite,
publie un digest quotidien et un hebdomadaire, et sert une page de lecture.

Aucune machine n'a besoin d'être allumée : tout s'exécute sur GitHub Actions.

**Ce dépôt contient le code, jamais les données.** Les éléments collectés, les notes
rédigées et la mémoire de déduplication vivent dans un dépôt privé, avec le vault
Obsidian où le système écrit.

## Le problème

Suivre l'actualité IA sur une trentaine de sources, c'est relire chaque jour des flux où
l'essentiel se noie dans le bruit. Et le volume ne dit rien de l'utilité : une source très
productive peut ne rien apporter, une source qui publie deux fois en trois semaines peut
être la plus précieuse. Sans mesure, impossible de savoir lesquelles garder.

## Comment il est fait

```
~34 sources → collecte (cron) → déduplication → scoring par profil → digest → vault
                                                                        ↓
                                                       page de lecture (statique)
```

| Étape | Où | Ce qui s'y joue |
|---|---|---|
| Collecte | `veille/feeds.py`, `veille/scrapers.py` | RSS, API Hacker News, scraping ciblé, sitemaps ; limitation par domaine (Reddit refuse deux requêtes à moins de 60 s d'écart) |
| Déduplication | `veille/dedupe.py` | Normalisation d'URL (paramètres de campagne, `www`, slash final) et mémoire de 60 jours |
| Scoring | `veille/summarize.py`, `veille/config.py` | Chaque élément est noté de 0 à 1 **contre un profil déclaré**, pas dans l'absolu |
| Rédaction | `veille/summarize.py`, `veille/vault.py` | Digest quotidien et hebdomadaire, écrits en Markdown dans le vault |
| Page | `veille/site.py`, `build_site.py` | Un seul fichier HTML statique, filtrage et recherche entièrement côté navigateur |
| Lecture d'article | `worker/lecture.js` | Worker Cloudflare qui récupère le texte d'un article, sur liste blanche |

### Deux décisions qui expliquent le reste

**Le score mesure l'intérêt pour un profil, pas l'importance générale.** Le profil est
écrit noir sur blanc dans `veille/config.py` et injecté dans le prompt. C'est là que se
fait le tri — pas dans la liste des sources. Une sortie de modèle majeure peut donc être
notée bas ici, et la page l'annonce au lecteur plutôt que de laisser croire à un jugement
absolu.

**Les sources sont arbitrées au rendement, pas au volume.** Mesuré source par source :
sept d'entre elles pesaient 26 % du volume collecté pour 5 % des éléments jugés utiles.
Elles ont été désactivées. Deux sources qui ne publient presque jamais ont été gardées,
parce que tout ce qu'elles publient est utile.

## La frontière privé / public

Le même générateur produit deux pages, distinguées par un seul drapeau :

| | Page personnelle | Page publique |
|---|---|---|
| Actualités, digests quotidiens, scores | oui | oui |
| Signets X et leurs fiches | oui | **non** |
| Favoris | oui | **non** |
| Développements d'articles déjà produits | oui | **non** |
| Digests hebdomadaires | oui | **non** |
| Profil dans le prompt embarqué | le vrai | un profil de lectorat, qui ne décrit personne |

Cette frontière tient à une seule fonction (`site._preparer(public=True)`), donc elle est
testée : `tests/test_frontiere_publique.py` construit la page publique et vérifie
qu'aucune donnée personnelle n'y apparaît — y compris en miroir, pour qu'un générateur qui
expurgerait tout ne passe pas le test.

Sur la page publique, développer un article se fait **avec la clé du lecteur** : elle reste
dans son navigateur, l'appel part de sa page vers le modèle, et l'hébergement ne coûte
rien. C'est un vrai compromis, pas un choix gratuit : sans clé, le bouton ne dispose que du
titre et de l'extrait, et le dit.

## Lancer le projet

```bash
pip install -r requirements.txt
cp .env.example .env        # puis renseigner GEMINI_API_KEY

python run_daily.py --dry-run    # collecte seule : ni modèle, ni écriture
python run_daily.py --no-vault   # digest en console, sans écrire de note
python build_site.py             # reconstruit la page de lecture
python build_site.py --public    # construit la version publiable
```

Les tests n'appellent aucun modèle et ne touchent à aucun vault :

```bash
pip install pytest ruff
python -m pytest -q
ruff check .
```

## Organisation du dépôt

```
veille/           le système : collecte, déduplication, scoring, rédaction, rendu
run_daily.py      digest quotidien           run_weekly.py    digest hebdomadaire
run_signets.py    relevé de signets X        run_favoris.py   mise à jour des favoris
build_site.py     construction de la page    sources.yaml     les sources et leur statut
worker/           Worker Cloudflare de lecture d'article
tests/            frontière privé/public, déduplication, rendu
```

## Ce que le système ne fait pas

- **Il ne republie pas les articles.** Il renvoie vers la source ; les résumés développés
  restent chez celui qui les demande.
- **Il ne collecte rien sur les lecteurs.** Page statique, sans compte, sans traceur, sans
  base de données.
- **Il ne réévalue pas son propre profil.** Le scoring est un filtre à sens unique : rien
  ne détecte aujourd'hui qu'un centre d'intérêt a changé. C'est la limite connue de la
  conception.
