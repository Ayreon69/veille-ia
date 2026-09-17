# Fontes embarquées

Trois familles, trois rôles, tels que découpés par Google Fonts :

| Fonte | Rôle | Sous-ensembles | Récupérée |
|---|---|---|---|
| **IBM Plex Sans**, variable 400–600 | ce qui se lit en continu | `latin`, `latin-ext` | 22/08/2026, `v23` |
| **Fraunces**, variable 400–600 | la titraille du jour | `latin` | 17/09/2026, `v38` |
| **IBM Plex Mono**, 400 et 500 | dates, scores, compteurs, étiquettes | `latin` | 17/09/2026, `v20` |

Fraunces et Plex Mono n'ont que le `latin` : la titraille est une date en français, et
le mono ne porte que des chiffres et des étiquettes. Le `latin-ext` de Fraunces pesait
59 Ko de caractères qui n'y paraîtront jamais.

Elles sont injectées par `veille/site.py` (`polices()`), et jamais chargées depuis
Google Fonts. Deux façons, selon la destination :

- le **fichier local** les embarque en base64 — c'est ce qui lui permet de s'ouvrir
  par double-clic, hors ligne, sans rien demander à personne ;
- le **site publié** les sert en fichiers voisins, depuis son propre domaine. La page
  est reconstruite tous les matins : 233 Ko de base64 repartaient à chaque visite,
  alors que des fichiers se revalident sans se retélécharger.

Trois raisons communes aux deux :

- **aucune requête vers un tiers**, donc aucune adresse IP de lecteur communiquée ;
- **aucun clignotement de police** au chargement ;
- le **site public ne trahit pas ses lecteurs** : un `<link>` vers `fonts.googleapis.com`
  enverrait leur adresse IP à Google, ce que la note *Site public* affirme ne pas faire.

Coût : environ 233 Ko de base64 par page, contre 103 Ko avant l'arrivée de Fraunces
et de Plex Mono le 17/09/2026. Le cyrillique et le grec ne sont pas
embarqués, ils ne serviraient jamais ici.

Si ces fichiers disparaissent, `polices()` renvoie une chaîne vide et la pile système
reprend la main : la page reste lisible, seulement moins caractérisée.

## Licence

Les trois familles sont sous SIL Open Font License 1.1 — voir `LICENSE.txt`.

- Copyright © 2017 IBM Corp. with Reserved Font Name "Plex".
- Copyright © 2019 The Fraunces Project Authors
  (https://github.com/undercasetype/Fraunces).

L'OFL autorise la redistribution, y compris embarquée dans une page web, à condition
que la licence accompagne la fonte. C'est l'objet de `LICENSE.txt`, présent dans ce
dossier et versionné avec elle.
