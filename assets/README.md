# Fontes embarquées

**IBM Plex Sans**, fonte variable, graisses 400 à 600, sous-ensembles `latin` et
`latin-ext` tels que découpés par Google Fonts. Récupérés le 22/08/2026 depuis
`fonts.gstatic.com`, version `v23`.

Elles sont encodées en base64 et injectées dans la page par `veille/site.py`
(`polices()`), et non chargées depuis Google Fonts. Trois raisons :

- la page reste **autonome** — elle s'ouvre par double-clic, hors ligne, comme le
  promet l'en-tête de `site.py` ;
- **aucune requête réseau** ajoutée, donc aucun clignotement de police au chargement ;
- le **site public ne trahit pas ses lecteurs** : un `<link>` vers `fonts.googleapis.com`
  enverrait leur adresse IP à Google, ce que la note *Site public* affirme ne pas faire.

Coût : environ 103 Ko de base64 par page. Le cyrillique et le grec ne sont pas
embarqués, ils ne serviraient jamais ici.

Si ces fichiers disparaissent, `polices()` renvoie une chaîne vide et la pile système
reprend la main : la page reste lisible, seulement moins caractérisée.

## Licence

SIL Open Font License 1.1 — voir `LICENSE.txt`.
Copyright © 2017 IBM Corp. with Reserved Font Name "Plex".

L'OFL autorise la redistribution, y compris embarquée dans une page web, à condition
que la licence accompagne la fonte. C'est l'objet de `LICENSE.txt`, présent dans ce
dossier et versionné avec elle.
