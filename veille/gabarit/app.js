(function(){
  const D = JSON.parse(document.getElementById('donnees').textContent);
  const flux = document.getElementById('flux');
  const champ = document.getElementById('recherche');
  const barre = document.getElementById('filtres');
  const barreVoies = document.getElementById('voies');
  const boutonSauver = document.getElementById('sauver');

  // Les articles déjà ouverts sont estompés : sur plusieurs jours d'archive, c'est
  // ce qui distingue le nouveau du déjà-vu.
  const CLE = 'veille-lus';
  let lus = new Set(JSON.parse(localStorage.getItem(CLE) || '[]'));
  const marquer = url => {
    lus.add(url);
    localStorage.setItem(CLE, JSON.stringify([...lus].slice(-4000)));
  };

  // ---- reprise de lecture ----
  // La première question du lecteur quotidien est « qu'est-ce que j'ai raté ? ». La
  // page ne pouvait pas y répondre : elle ouvrait sur le jour même, sans savoir si on
  // l'avait déjà lu. Elle retient donc la date de la visite précédente — dans le
  // navigateur du lecteur, rien n'est envoyé nulle part.
  //
  // Deux stockages, et c'est nécessaire : localStorage retient la date de la dernière
  // visite d'un jour à l'autre, sessionStorage fige le repère le temps de l'onglet.
  // Sans le second, recharger la page effacerait le bandeau qu'on est en train de
  // lire — la visite précédente serait devenue « il y a dix secondes ».
  const CLE_VISITE = 'veille-derniere-visite';
  const CLE_REPERE = 'veille-repere-visite';
  let repere = null;
  try {
    repere = sessionStorage.getItem(CLE_REPERE);
    if (repere === null) {
      repere = localStorage.getItem(CLE_VISITE) || '';
      sessionStorage.setItem(CLE_REPERE, repere);
    }
    localStorage.setItem(CLE_VISITE, new Date().toISOString());
  } catch (e) {
    repere = repere || '';   // navigation privée, stockage refusé : pas de bandeau
  }
  const seuilVisite = repere ? Date.parse(repere) : NaN;

  // À la toute première visite, tout est nouveau : le dire n'apprendrait rien, et
  // marquer quarante items « nouveau » ne distinguerait plus rien du tout.
  const estNouveau = i => {
    if (isNaN(seuilVisite)) return false;
    const t = Date.parse(i.date);
    return !isNaN(t) && t > seuilVisite;
  };

  const depuis = ms => {
    const h = Math.floor(ms / 3600000);
    if (h < 1) return "il y a moins d'une heure";
    if (h < 24) return `il y a ${h} heure${h > 1 ? 's' : ''}`;
    const j = Math.round(h / 24);
    return j <= 1 ? 'hier' : `il y a ${j} jours`;
  };

  // ---- favoris ----
  // L'item est stocké EN ENTIER, pas par son URL : la page n'affiche que 90 jours, et
  // un favori doit rester consultable une fois sa journée sortie de la fenêtre. Il est
  // alors rendu depuis cette copie, sans rien devoir aux données de la page.
  //
  // `retires` est la contrepartie nécessaire : les favoris arrivent de deux côtés — le
  // navigateur et le vault — et sans trace datée des retraits, chaque reconstruction du
  // site ferait revenir ce qui vient d'être enlevé. Le retrait l'emporte s'il est
  // postérieur à la mise en favori ; remettre en favori suffit donc à annuler.
  const CLE_FAV = 'veille-favoris';
  const CLE_RETIRES = 'veille-favoris-retires';
  const lire = (cle, defaut) => {
    try { return JSON.parse(localStorage.getItem(cle)) || defaut; } catch { return defaut; }
  };
  let favoris = lire(CLE_FAV, {});
  let retires = lire(CLE_RETIRES, {});

  (D.favoris || []).forEach(f => {
    const retire = retires[f.url];
    if (retire && (f.favori_le || '') <= retire) return;
    const local = favoris[f.url];
    if (!local || (f.favori_le || '') < (local.favori_le || '')) favoris[f.url] = f;
  });

  const ecrireLocal = () => {
    try {
      localStorage.setItem(CLE_FAV, JSON.stringify(favoris));
      localStorage.setItem(CLE_RETIRES, JSON.stringify(retires));
      return true;
    } catch (e) {
      alert("Favori non enregistré : le stockage du navigateur est plein.");
      return false;
    }
  };
  ecrireLocal();   // fige la fusion vault + navigateur

  // Servie par le serveur local, la page pousse les favoris dans le vault d'elle-même :
  // plus rien à télécharger, plus rien à ramasser. Le bouton « Sauvegarder » ne
  // réapparaît que si cet envoi échoue — mieux vaut un bouton de secours qu'une fausse
  // impression d'être enregistré.
  let envoiKO = false;

  function versLeVault(){
    fetch('/api/favoris', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({favoris: listeFavoris(), retires: retires})
    }).then(r => {
      if (!r.ok) throw new Error(r.status);
      envoiKO = false;
      boutonSauver.hidden = true;
    }).catch(() => {
      envoiKO = true;
      boutonSauver.hidden = vue !== 'favoris';
      boutonSauver.title = "L'enregistrement automatique a échoué — cliquer pour "
        + "télécharger un export, repris à la prochaine synchronisation.";
    });
  }

  const sauverFavoris = () => {
    const ok = ecrireLocal();
    if (LOCAL) versLeVault();
    return ok;
  };

  const listeFavoris = () => Object.values(favoris);

  // ---- développements ----
  // Servie en http://, la page peut demander au serveur local d'appeler le modèle.
  // Ouverte par double-clic sur le fichier, elle ne le peut pas — mais elle affiche
  // quand même les développements déjà produits, embarqués à la construction.
  const SERVI = location.protocol === 'http:' || location.protocol === 'https:';

  // Le site public est servi en https lui aussi : le protocole ne suffit donc pas à
  // savoir si l'API locale est joignable. `LOCAL` désigne le site personnel servi par
  // veille.serveur, `PUBLIC` la page publiée où c'est le lecteur qui apporte sa clé.
  const PUBLIC = !!D.public;
  const LOCAL = SERVI && !PUBLIC;

  const CLE_DEV = 'veille-developpements';
  const dev = Object.assign({}, D.developpements || {}, lire(CLE_DEV, {}));
  const memoriserDev = () => {
    // Le lecteur d'un site public garde ses propres développements : les siens, pas
    // ceux d'un autre. Le quota peut être atteint sur un très gros historique — ce
    // n'est pas une raison pour perdre le développement qu'on vient d'afficher.
    try { localStorage.setItem(CLE_DEV, JSON.stringify(dev)); } catch (e) {}
  };

  const LIBELLES = {
    prio:'Claude & Co', labs:'Labos', outils:'Outils',
    agregateur:'Agrégateurs', analyse:'Analyses', francophone:'Francophone',
    // Ne sert que dans les favoris, qui mêlent actualités et signets. Ailleurs le
    // compteur tombe à zéro et la puce est retirée d'elle-même.
    signets:'Signets'
  };

  // Deux vues étanches. Les signets ne sont pas une catégorie de la veille : ce sont mes
  // propres choix, ils se noieraient parmi quarante actualités par jour. Aucun item
  // n'apparaît dans les deux onglets.
  // Publiquement, il n'y a qu'une vue : les signets et les favoris sont des choix
  // personnels, ils ne sont pas dans les données envoyées.
  // Les digests hebdomadaires ne sont pas publiés ; la raison, chiffres à l'appui, est
  // dans _preparer() côté Python. Elle n'est pas répétée ici : ce commentaire-ci part
  // dans la page publique, et n'a donc pas à nommer ce qu'il protège.
  const SEMAINES = D.semaines || [];
  let semaineActive = 0;

  const VUES = D.public
    ? {veille:'Veille'}
    : {veille:'Veille', semaine:'Semaine', signets:'Mes signets', favoris:'Favoris'};
  const estSignet = i => i.categorie === 'signets';

  // Voies cumulatives : « + Utile » contient l'essentiel, et laisse passer les items
  // non notés — une archive antérieure au scoring ne doit pas disparaître en silence.
  const VOIES = {
    essentiel: {nom:'Essentiel', ok: i => i.voie === 'essentiel'},
    utile:     {nom:'+ Utile',   ok: i => i.voie !== 'bruit'},
    tout:      {nom:'Tout',      ok: () => true}
  };

  let vue = 'veille';
  // Sans aucun item noté, s'ouvrir sur une voie filtrée donnerait une page blanche.
  let voie = D.notes ? 'utile' : 'tout';
  let filtre = 'tout';
  let requete = '';
  let tri = 'pertinence';

  // ---- portée temporelle ----
  // Déclarée ici et non dans le bloc « navigation par jour » plus bas : les compteurs
  // de voie et de sujet sont calculés dès l'initialisation, avant que ce bloc ne soit
  // évalué. Les y laisser donnerait une ReferenceError de zone morte temporelle.
  const DATES = D.jours.map(j => j.date);
  const PAR_DATE = new Map(D.jours.map(j => [j.date, j]));
  let jourActif = DATES[0] || null;
  let dernierJour = jourActif;   // pour revenir d'un aller-retour par « Tout »

  // Une recherche qui ne fouillerait que la journée affichée ne servirait à rien : on
  // cherche justement ce dont on ne sait plus quel jour c'était. Elle porte donc sur
  // toute l'archive, et la barre le dit au lieu de le faire en douce.
  const surToutLArchive = () => jourActif === null || !!requete;

  // Les signets ne sont pas un flux quotidien mais une petite collection choisie : les
  // paginer par jour ferait chercher à l'aveugle. Ils restent affichés en entier.
  const joursAffiches = () => (vue === 'signets' || surToutLArchive())
    ? D.jours : D.jours.filter(j => j.date === jourActif);

  // Déclaré ici, avec la portée, plutôt qu'à côté de `sujetOk` : les compteurs des
  // filtres s'en servent, et ils sont calculés dès l'initialisation.
  const texteOk = i =>
    !requete || [i.titre, i.source_nom, i.extrait, i.analyse, i.justification]
      .join(' ').toLowerCase().includes(requete);

  const tous = D.jours.flatMap(j => j.items);
  const parUrl = new Map(tous.map(i => [i.url, i]));
  // Les favoris ne sont pas un sous-ensemble de la page : certains n'y sont plus.
  // Le lot suit la journée affichée, sans quoi les compteurs des filtres annonceraient
  // l'archive entière au-dessus d'une liste qui ne montre qu'un jour.
  const lot = () => (vue === 'favoris'
    ? listeFavoris()
    : joursAffiches().flatMap(j => j.items)
        .filter(i => estSignet(i) === (vue === 'signets'))
  ).filter(texteOk);

  // Règle unique : un compteur décrit la liste qu'il surplombe. Tous se lisent donc
  // dans la journée affichée ET dans la recherche en cours. Ceux de sujet se lisent en
  // plus dans la voie active : afficher « Labos 14 » alors que la voie n'en laisse
  // passer que 3 serait trompeur. Les compteurs de voie, eux, ignorent le sujet —
  // c'est l'axe primaire. Seuls les onglets échappent à la règle : ils comptent des
  // collections entières, et servent à choisir entre elles.
  const compte = cle => {
    const restants = lot().filter(VOIES[voie].ok);
    return cle === 'tout' ? restants.length
      : cle === 'prio' ? restants.filter(i => i.prioritaire).length
      : restants.filter(i => i.categorie === cle).length;
  };

  function rendreOnglets(){
    onglets.innerHTML = Object.entries(VUES).map(([c, nom]) => {
      const n = c === 'favoris' ? listeFavoris().length
        : c === 'semaine' ? SEMAINES.length
        : tous.filter(i => estSignet(i) === (c === 'signets')).length;
      return `<button class="onglet" role="tab" data-vue="${c}" aria-selected="${c === vue}">`
        + `${nom}<span class="n">${n}</span></button>`;
    }).join('');
  }

  function rendreVoies(){
    barreVoies.innerHTML = '<span class="etiq">Voie</span>' + Object.entries(VOIES)
      .map(([c, v]) => `<button class="puce" data-cle="${c}" aria-pressed="${c === voie}">`
        + `${v.nom}<span class="n">${lot().filter(v.ok).length}</span></button>`)
      .join('');
  }

  const cles = ['tout','prio', ...Object.keys(LIBELLES).filter(c => c !== 'prio')];

  function rendreSujets(){
    // Un sujet vide dans la voie courante est retiré plutôt que laissé à zéro : sinon
    // la rangée se remplit de boutons qui ne donnent rien.
    if (!cles.filter(c => c !== 'tout' && compte(c) > 0).includes(filtre)) filtre = 'tout';
    barre.innerHTML = '<span class="etiq">Sujet</span>' + cles
      .filter(c => c === 'tout' || compte(c) > 0)
      .map(c => `<button class="puce" data-cle="${c}" aria-pressed="${c === filtre}">`
        + `${c === 'tout' ? 'Tout' : LIBELLES[c]}<span class="n">${compte(c)}</span></button>`)
      .join('');
  }
  rendreOnglets();
  rendreVoies();
  rendreSujets();

  onglets.addEventListener('click', e => {
    const b = e.target.closest('.onglet');
    if (!b || b.dataset.vue === vue) return;
    vue = b.dataset.vue;
    // La voie disparaît hors de la veille, et pour la même raison dans les deux cas :
    // un signet comme un favori sont des choix que j'ai faits moi-même, ce n'est pas
    // au score de décider de les masquer. Le sujet, lui, reste utile dans les favoris,
    // qui mélangent actualités et signets ; il n'en a aucun dans l'onglet signets, où
    // tout est de la même catégorie.
    const veille = vue === 'veille';
    const hebdo = vue === 'semaine';
    barreVoies.hidden = !veille;
    barre.hidden = vue === 'signets' || hebdo;
    // Filtrer ou trier une synthèse rédigée n'a aucun sens : les contrôles disparaissent
    // au lieu de rester là sans effet.
    champ.hidden = hebdo;
    selecteurTri.hidden = hebdo;
    boutonSauver.hidden = (LOCAL && !envoiKO) || vue !== 'favoris';
    if (!veille) { voie = 'tout'; filtre = 'tout'; }
    else if (voie === 'tout' && D.notes) voie = 'utile';
    rendreOnglets(); rendreVoies(); rendreSujets(); rendre();
  });

  barreVoies.addEventListener('click', e => {
    const b = e.target.closest('.puce');
    if (!b) return;
    voie = b.dataset.cle;
    barreVoies.querySelectorAll('.puce').forEach(p =>
      p.setAttribute('aria-pressed', p.dataset.cle === voie));
    rendreSujets();   // les compteurs de sujet dépendent de la voie
    rendre();
  });

  barre.addEventListener('click', e => {
    const b = e.target.closest('.puce');
    if (!b) return;
    filtre = b.dataset.cle;
    barre.querySelectorAll('.puce').forEach(p =>
      p.setAttribute('aria-pressed', p.dataset.cle === filtre));
    rendre();
  });

  champ.addEventListener('input', () => {
    requete = champ.value.toLowerCase().trim();
    // Saisir un mot change à la fois la portée — la journée cède la place à l'archive
    // entière — et le décompte de chaque voie. Les deux rangées sont donc redessinées.
    rendreVoies(); rendreSujets(); rendre();
  });

  const selecteurTri = document.getElementById('tri');
  selecteurTri.addEventListener('change', () => { tri = selecteurTri.value; rendre(); });

  // L'ordre par pertinence est déjà celui du fichier, calculé à la génération : Claude
  // d'abord, puis le score. Le tri par date ne s'applique qu'à la demande.
  const ordonner = items => {
    if (tri === 'pertinence') {
      // « Pertinence » n'a rien à classer dans les favoris : ils sont tous pertinents,
      // c'est moi qui les ai choisis. L'ordre qui informe est celui de l'ajout.
      return vue === 'favoris'
        ? [...items].sort((a, b) => (b.favori_le || '').localeCompare(a.favori_le || ''))
        : items;
    }
    const cle = i => i.date || '';
    const trie = [...items].sort((a, b) => cle(b).localeCompare(cle(a)));
    return tri === 'date-inverse' ? trie.reverse() : trie;
  };

  const sujetOk = i =>
    filtre === 'tout' || (filtre === 'prio' ? i.prioritaire : i.categorie === filtre);
  const garde = i =>
      vue === 'favoris' ? sujetOk(i) && texteOk(i)
    : vue === 'signets' ? estSignet(i) && texteOk(i)
    : !estSignet(i) && VOIES[voie].ok(i) && sujetOk(i) && texteOk(i);

  const heure = iso => {
    if (!iso) return '';
    const d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});
  };

  const dateComplete = iso => {
    if (!iso) return '';
    const d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleDateString('fr-FR', {day:'numeric', month:'short', year:'numeric'});
  };

  const echapper = s => { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; };

  // Une ancre par élément, pour pouvoir envoyer un lien vers UN article et le
  // retrouver demain. L'URL de l'article ferait une ancre valide mais illisible et
  // longue de 200 caractères ; on en prend une empreinte courte et stable (FNV-1a),
  // qui ne change pas d'une construction à l'autre puisqu'elle ne dépend que de l'URL.
  const ancre = url => {
    let h = 0x811c9dc5;
    for (let k = 0; k < url.length; k++) {
      h ^= url.charCodeAt(k);
      h = Math.imul(h, 0x01000193) >>> 0;
    }
    return 'i' + h.toString(36);
  };
  const parAncre = new Map();

  // Classe de mise en avant du verdict : « Utile » et « À tester » sont des actions,
  // « Pour info » et « Peu d'intérêt » ne méritent pas d'attirer l'œil.
  const RANG = {'Utile':'v-fort', 'À tester':'v-fort', 'Pour info':'v-moyen', "Peu d'intérêt":'v-faible'};

  const domaine = url => { try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return ''; } };

  function carteSignet(i){
    // Date complète, et non l'heure seule : les signets remontent à plusieurs années,
    // et ils sont archivés au jour de leur import, pas à celui du tweet.
    const q = dateComplete(i.date);
    return `<details class="item signet${i.prioritaire ? ' prio' : ''}${lus.has(i.url) ? ' lu' : ''}"`
      + ` data-url="${echapper(i.url)}"><summary>`
      + `<span class="t">${echapper(i.titre)}</span>`
      + `<span class="ligne"><span class="src">${echapper(i.source_nom)}</span>`
      + (estNouveau(i) ? `<span class="neuf">nouveau</span>` : '')
      + (q ? `<span>${q}</span>` : '')
      + (i.verdict ? `<span class="verdict ${RANG[i.verdict] || 'v-moyen'}">${echapper(i.verdict)}</span>` : '')
      + (i.score != null ? `<span class="score ${i.voie}" title="Intérêt estimé pour ton profil (0 à 1)">${i.score.toFixed(2)}</span>` : '')
      + `</span></summary><div class="deplie">`
      + (i.analyse ? `<p class="analyse">${echapper(i.analyse)}</p>` : '')
      + (i.justification ? `<p class="pourtoi"><b>Pour toi</b> — ${echapper(i.justification)}</p>` : '')
      + `<div class="pieds">`
      + (i.cible ? `<a href="${echapper(i.cible)}" target="_blank" rel="noopener">↗ ${echapper(domaine(i.cible))}</a>` : '')
      + `<a href="${echapper(i.url)}" target="_blank" rel="noopener">voir le tweet</a>`
      + `</div></div></details>`;
  }

  function etoile(i){
    const marque = !!favoris[i.url];
    return `<button class="etoile" data-url="${echapper(i.url)}" aria-pressed="${marque}"`
      + ` title="${marque ? 'Retirer des favoris' : 'Mettre en favori'}"`
      + ` aria-label="${marque ? 'Retirer des favoris' : 'Mettre en favori'}">`
      + `${marque ? '★' : '☆'}</button>`;
  }

  // Le bouton était un « + » de 19 px dans le coin de la carte, à 30 % d'opacité
  // tant qu'on ne survolait pas. Il fait pourtant la chose la plus intéressante du
  // site — un résumé complet et un exemple d'usage — et personne ne pouvait le
  // deviner. Il porte désormais son nom, en toutes lettres, sous la carte.
  const LIBELLE_DEV = {
    pret: 'Développer',
    fait: 'Voir le développement',
    ouvert: 'Replier',
  };

  function boutonDev(i){
    const fait = !!dev[i.url];
    return `<button class="developper" data-url="${echapper(i.url)}" data-fait="${fait}"`
      + ` aria-expanded="false"`
      + ` title="Résumé complet en français, et un exemple d'usage concret">`
      + `${fait ? LIBELLE_DEV.fait : LIBELLE_DEV.pret}</button>`;
  }

  function carte(i){
    parAncre.set(ancre(i.url), i.url);
    return `<div class="enveloppe" id="${ancre(i.url)}">`
      + ((estSignet(i) && i.analyse) ? carteSignet(i) : carteLien(i))
      + `<div class="actions">${boutonDev(i)}`
      + `<button class="lien-ancre" data-ancre="${ancre(i.url)}"`
      + ` title="Copier un lien vers cet élément">Lien</button>`
      + `${PUBLIC ? '' : etoile(i)}</div>`
      + `<div class="developpement" hidden></div></div>`;
  }

  // Le score sort de la ligne de méta, où il flottait à droite parmi cinq autres
  // étiquettes, pour prendre une colonne à lui, à gauche. C'est le seul chiffre de la
  // page, celui par lequel la liste est triée : il doit se lire en descendant la
  // colonne, sans lire les titres.
  function carteLien(i){
    const h = heure(i.date);
    return `<a class="item${i.prioritaire ? ' prio' : ''}${lus.has(i.url) ? ' lu' : ''}"`
      + ` href="${echapper(i.url)}" target="_blank" rel="noopener" data-url="${echapper(i.url)}">`
      + (i.score != null
        ? `<span class="score ${i.voie}" title="Intérêt estimé pour ce site, de 0 à 1">${i.score.toFixed(2)}</span>`
        : `<span class="score vide" title="Élément antérieur au scoring">—</span>`)
      + `<div class="corps-item">`
      + `<h3>${echapper(i.titre)}</h3>`
      + `<div class="ligne"><span class="src">${echapper(i.source_nom)}</span>`
      + (estNouveau(i) ? `<span class="neuf">nouveau</span>` : '')
      + (h ? `<span>${h}</span>` : '')
      + (i.categorie && !estSignet(i) ? `<span class="cat">${echapper(LIBELLES[i.categorie] || i.categorie)}</span>` : '')
      // Inutile dans l'onglet signets : tout y est un tweet, la mention n'informe plus.
      + (i.titre_utilisateur && !estSignet(i) ? `<span class="avis" title="Titre rédigé par un utilisateur : affirmation, pas fait vérifié">titre d'utilisateur</span>` : '')
      + `</div>`
      + (i.extrait ? `<p class="extrait">${echapper(i.extrait)}</p>` : '')
      + `</div></a>`;
  }

  // Les favoris s'étalent sur des mois : les regrouper par journée émietterait la
  // liste en sections d'un seul élément. Une section unique, et le tri fait le reste.
  function sectionFavoris(){
    const items = ordonner(listeFavoris().filter(garde));
    if (!items.length) return {n: 0, html: ''};
    return {
      n: items.length,
      html: `<section class="jour"><h2>Mes favoris<span class="n">${items.length}</span></h2>`
        + items.map(carte).join('') + `</section>`
    };
  }

  // ---- navigation par jour -----------------------------------------------
  // Dix-neuf journées empilées, c'est plusieurs milliers de pixels de défilement pour
  // atteindre avant-hier — alors que l'usage courant est de lire le jour même. La page
  // s'ouvre donc sur la journée la plus récente. `jourActif === null` rétablit
  // l'empilement complet, gardé sous le bouton « Tout » : la vue d'ensemble reste utile
  // pour balayer une semaine, elle ne doit simplement plus être le défaut.
  let moisVu = null;

  const navJour = document.getElementById('nav-jour');
  const calendrier = document.getElementById('calendrier');
  const btDate = document.getElementById('datejour');

  // Compté dans la voie et le sujet actifs, comme les autres compteurs de la page :
  // annoncer 138 sur une journée pour n'en afficher que 12 serait trompeur.
  const compteJour = j =>
    j.items.filter(i => !estSignet(i) && VOIES[voie].ok(i) && sujetOk(i)).length;

  // « Aujourd'hui », « Hier », « Il y a 4 jours » — compté depuis le vrai jour du
  // lecteur et non depuis la dernière date de l'archive : une page ouverte le lundi
  // doit dire « il y a 3 jours » de son édition du vendredi, pas « aujourd'hui ».
  const distance = date => {
    const aujourdhui = new Date(); aujourdhui.setHours(0, 0, 0, 0);
    const [a, m, j] = date.split('-').map(Number);
    const n = Math.round((aujourdhui - new Date(a, m - 1, j)) / 86400000);
    return n === 0 ? "Aujourd'hui" : n === 1 ? 'Hier' : n === 2 ? 'Avant-hier'
      : n > 0 ? `Il y a ${n} jours` : 'À venir';
  };

  const cleDate = (an, mois, jour) =>
    `${an}-${String(mois + 1).padStart(2, '0')}-${String(jour).padStart(2, '0')}`;

  function rendreNavJour(){
    navJour.hidden = vue !== 'veille';
    if (navJour.hidden) { fermerCalendrier(); return; }

    const i = DATES.indexOf(jourActif);
    const large = surToutLArchive();
    document.getElementById('prec').disabled = large || i < 0 || i >= DATES.length - 1;
    document.getElementById('suiv').disabled = large || i <= 0;
    btDate.disabled = !!requete;

    // Le bouton portait la date en toutes lettres ; elle est montée dans la titraille
    // le 2026-09-17. Il dit maintenant à quelle distance de soi on se trouve — la seule
    // chose que la date écrite ne dit pas, et celle qu'on cherche en arrivant.
    const jours = `${DATES.length} jour${DATES.length > 1 ? 's' : ''}`;
    btDate.innerHTML = requete
      ? `Recherche sur ${jours}`
      : jourActif === null
        ? `Toutes les journées<span class="n">${DATES.length}</span>`
        : `${echapper(distance(jourActif))}`
          + `<span class="n">${compteJour(PAR_DATE.get(jourActif))}</span>`;
    document.getElementById('tousjours').setAttribute('aria-pressed', jourActif === null);
  }

  const allerA = date => {
    jourActif = date;
    if (date !== null) dernierJour = date;
    fermerCalendrier();
    // Les nombres des deux rangées de filtres viennent de changer avec la journée.
    rendreVoies(); rendreSujets(); rendre();
    window.scrollTo(0, 0);
  };

  const decaler = n => {
    const i = DATES.indexOf(jourActif) + n;
    if (i >= 0 && i < DATES.length) allerA(DATES[i]);
  };

  function fermerCalendrier(){
    calendrier.hidden = true;
    btDate.setAttribute('aria-expanded', 'false');
  }

  function rendreCalendrier(){
    const {an, mois} = moisVu;
    const premier = new Date(an, mois, 1);
    const decalage = (premier.getDay() + 6) % 7;              // semaine commençant lundi
    const nb = new Date(an, mois + 1, 0).getDate();
    const courant = `${an}-${String(mois + 1).padStart(2, '0')}`;

    let cases = '';
    for (let k = 0; k < decalage; k++) cases += `<span class="cal-case"></span>`;
    for (let d = 1; d <= nb; d++) {
      const cle = cleDate(an, mois, d);
      const j = PAR_DATE.get(cle);
      cases += j
        ? `<button class="cal-case plein" data-date="${cle}"`
          + `${cle === jourActif ? ' aria-current="date"' : ''}>`
          + `${d}<span class="n">${compteJour(j)}</span></button>`
        : `<button class="cal-case" disabled>${d}</button>`;
    }

    calendrier.innerHTML =
      `<div class="cal-tete">`
      + `<button class="fleche" data-mois="-1" aria-label="Mois précédent"`
      + `${DATES[DATES.length - 1].slice(0, 7) < courant ? '' : ' disabled'}>&lsaquo;</button>`
      + `<strong>${premier.toLocaleDateString('fr-FR', {month:'long', year:'numeric'})}</strong>`
      + `<button class="fleche" data-mois="1" aria-label="Mois suivant"`
      + `${DATES[0].slice(0, 7) > courant ? '' : ' disabled'}>&rsaquo;</button>`
      + `</div><div class="cal-grille">`
      + ['lun','mar','mer','jeu','ven','sam','dim'].map(x => `<span class="jsem">${x}</span>`).join('')
      + cases + `</div>`;
  }

  document.getElementById('prec').addEventListener('click', () => decaler(1));
  document.getElementById('suiv').addEventListener('click', () => decaler(-1));

  document.getElementById('tousjours').addEventListener('click', () => {
    allerA(jourActif === null ? (dernierJour || DATES[0] || null) : null);
  });

  btDate.addEventListener('click', () => {
    if (!calendrier.hidden) return fermerCalendrier();
    const [a, m] = (jourActif || DATES[0] || '').split('-').map(Number);
    if (!a) return;
    moisVu = {an: a, mois: m - 1};
    rendreCalendrier();
    calendrier.hidden = false;
    btDate.setAttribute('aria-expanded', 'true');
  });

  calendrier.addEventListener('click', e => {
    const saut = e.target.closest('[data-mois]');
    if (saut) {
      const d = new Date(moisVu.an, moisVu.mois + Number(saut.dataset.mois), 1);
      moisVu = {an: d.getFullYear(), mois: d.getMonth()};
      return rendreCalendrier();
    }
    const case_ = e.target.closest('.cal-case.plein');
    if (case_) allerA(case_.dataset.date);
  });

  document.addEventListener('click', e => {
    if (!calendrier.hidden && !(e.target instanceof Element && e.target.closest('.nav-jour')))
      fermerCalendrier();
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !calendrier.hidden) return fermerCalendrier();
    // Les flèches appartiennent au champ de saisie tant qu'on y écrit. `closest`
    // n'existe que sur un Element : la cible d'un keydown peut être le document.
    if (e.target instanceof Element && e.target.closest('input, select, textarea')) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    const recule = e.key === 'ArrowLeft';
    if (vue === 'semaine') {
      e.preventDefault();
      return allerASemaine(semaineActive + (recule ? 1 : -1));
    }
    if (vue !== 'veille' || surToutLArchive()) return;
    e.preventDefault();
    decaler(recule ? 1 : -1);
  });

  // ---- navigation hebdomadaire ----------------------------------------------
  // Même barre que pour les jours, mais une liste plutôt qu'un calendrier : une
  // semaine n'a pas de place dans une grille de mois, et il y en aura toujours peu.
  const navSemaine = document.getElementById('nav-semaine');
  const listeSemaines = document.getElementById('liste-semaines');
  const btSemaine = document.getElementById('sem-libelle');

  const fermerListeSemaines = () => {
    listeSemaines.hidden = true;
    btSemaine.setAttribute('aria-expanded', 'false');
  };

  function rendreNavSemaine(){
    navSemaine.hidden = vue !== 'semaine';
    if (navSemaine.hidden) return fermerListeSemaines();
    document.getElementById('sem-prec').disabled = semaineActive >= SEMAINES.length - 1;
    document.getElementById('sem-suiv').disabled = semaineActive <= 0;
    btSemaine.disabled = SEMAINES.length < 2;
    btSemaine.textContent = SEMAINES.length
      ? SEMAINES[semaineActive].libelle
      : 'Aucune semaine archivée';
  }

  const allerASemaine = i => {
    if (i < 0 || i >= SEMAINES.length) return;
    semaineActive = i;
    fermerListeSemaines();
    rendre();
    window.scrollTo(0, 0);
  };

  document.getElementById('sem-prec').addEventListener('click', () => allerASemaine(semaineActive + 1));
  document.getElementById('sem-suiv').addEventListener('click', () => allerASemaine(semaineActive - 1));

  btSemaine.addEventListener('click', () => {
    if (!listeSemaines.hidden) return fermerListeSemaines();
    listeSemaines.innerHTML = SEMAINES.map((s, i) =>
      `<button role="option" data-i="${i}" aria-current="${i === semaineActive}">`
      + `${echapper(s.libelle)}</button>`).join('');
    listeSemaines.hidden = false;
    btSemaine.setAttribute('aria-expanded', 'true');
  });

  listeSemaines.addEventListener('click', e => {
    const b = e.target.closest('[data-i]');
    if (b) allerASemaine(Number(b.dataset.i));
  });

  document.addEventListener('click', e => {
    if (!listeSemaines.hidden && !(e.target instanceof Element && e.target.closest('#nav-semaine')))
      fermerListeSemaines();
  });

  // Un renvoi du digest hebdo vers une journée bascule sur elle, dans l'onglet Veille.
  // C'est ce qui relie les deux vues : la synthèse dit quoi, la journée montre d'où.
  flux.addEventListener('click', e => {
    const b = e.target instanceof Element && e.target.closest('.lien-jour');
    if (!b || b.disabled) return;
    vue = 'veille';
    barreVoies.hidden = false;
    barre.hidden = false;
    champ.hidden = false;
    selecteurTri.hidden = false;
    boutonSauver.hidden = true;
    rendreOnglets();
    allerA(b.dataset.date);
  });

  function rendreSemaine(){
    if (!SEMAINES.length) {
      flux.innerHTML = `<p class="vide">Aucun digest hebdomadaire pour l'instant.<br><br>`
        + `Le premier est écrit le lundi matin qui suit une semaine complète, `
        + `ou à la demande avec <code>python .veille/run_weekly.py</code>.</p>`;
      return resumer(0, 'rien à lire', 'semaine');
    }
    const s = SEMAINES[semaineActive];
    flux.innerHTML = `<section class="jour hebdo"><div class="corps">${s.html}</div></section>`;
    // Une journée sortie de la fenêtre d'affichage n'est plus atteignable : le renvoi
    // reste lisible, mais cesse d'être un bouton qui ne mènerait nulle part.
    flux.querySelectorAll('.lien-jour').forEach(b => {
      if (!PAR_DATE.has(b.dataset.date)) b.disabled = true;
    });
    resumer(SEMAINES.length, s.libelle, 'semaine');
  }

  function rendre(){
    // Les deux barres se rafraîchissent avant tout retour anticipé : chacune se masque
    // d'elle-même hors de sa vue, encore faut-il qu'on l'appelle.
    rendreNavJour();
    rendreNavSemaine();
    if (vue === 'semaine') return rendreSemaine();
    if (vue === 'favoris') return rendreFavoris();
    const portee = joursAffiches();
    let visibles = 0;
    const html = portee.map(j => {
      const items = ordonner(j.items.filter(garde));
      if (!items.length) return '';
      visibles += items.length;
      // Le digest rédigé porte sur la veille : il n'a rien à faire dans les signets.
      const digests = (vue === 'veille' && filtre === 'tout' && !requete)
        ? j.digests.map(d => `<details class="digest"${j === portee[0] ? ' open' : ''}>`
            + `<summary>Digest${d.heure ? ' de ' + d.heure : ''}</summary>`
            + `<div class="corps">${d.html}</div></details>`).join('')
        : '';
      return `<section class="jour"><h2>${echapper(j.libelle)}`
        + `<span class="n">${items.length}</span></h2>${digests}`
        + items.map(carte).join('') + `</section>`;
    }).join('');

    const aucunSignet = vue === 'signets' && !tous.some(estSignet);
    // Sur une seule journée, le titre de section répète mot pour mot la barre de
    // navigation juste au-dessus. Deux fois la même date, c'est une de trop.
    flux.classList.toggle('un-jour', vue === 'veille' && !surToutLArchive());
    flux.innerHTML = html || (aucunSignet
      ? `<p class="vide">Aucun signet relevé pour l'instant.<br><br>`
        + `Lancer une fois <code>python run_signets.py --connexion</code> pour ouvrir la `
        + `session X, puis le relevé se fait tout seul à chaque synchronisation.</p>`
      : portee.length === 1 && !requete
        ? `<p class="vide">Rien ce jour-là dans cette voie.<br><br>`
          + `Élargir la voie ci-dessus, ou passer à la journée précédente avec &lsaquo;.</p>`
        : `<p class="vide">Aucun élément ne correspond.</p>`);
    const archive = `sur ${D.jours.length} jour${D.jours.length > 1 ? 's' : ''}`;
    resumer(
      visibles,
      vue === 'signets' ? VUES.signets
        : requete ? `« ${requete} »`
        : surToutLArchive() ? 'Toutes les journées'
        : PAR_DATE.get(jourActif).libelle,
      'élément',
      (vue === 'signets' || surToutLArchive() || requete) ? archive : '',
    );
  }

  function rendreFavoris(){
    const section = sectionFavoris();
    flux.innerHTML = section.html || (listeFavoris().length
      ? `<p class="vide">Aucun favori ne correspond.</p>`
      : `<p class="vide">Aucun favori pour l'instant.<br><br>`
        + `Cliquer sur l'étoile ☆ en haut d'un élément, dans n'importe quel onglet, `
        + `pour le mettre de côté. Il restera ici même quand sa journée sera sortie `
        + `de l'archive.</p>`);
    resumer(section.n, VUES.favoris, 'favori');
  }

  // Une seule ligne disait tout : « 138 éléments · Mardi 16 septembre · maj … ». Elle
  // est séparée en trois le 2026-09-17, parce que les trois ne changent pas au même
  // rythme : le titre est ce qu'on lit, les compteurs ce qu'on vient de filtrer, et la
  // fraîcheur de la page ne bouge pas de la visite — elle vit dans la barre d'état.
  const resumer = (n, titre, unite = 'élément', etendue = '') => {
    document.getElementById('titraille').textContent = titre;
    document.getElementById('compteurs').innerHTML =
      `<span><b>${n}</b> ${unite}${n > 1 ? 's' : ''}</span>`
      + (etendue ? `<span>${echapper(etendue)}</span>` : '');
  };

  const itemPour = url => parUrl.get(url) || favoris[url] || null;

  // Transposition du convertisseur markdown du générateur : sur la page publique, le
  // texte arrive du modèle directement dans le navigateur, il n'est jamais passé par
  // Python. Même sous-ensemble, mêmes règles — titres, listes, gras, code, blocs.
  function markdownHtml(md){
    const sortie = [];
    let dansListe = false, dansBloc = false;
    const enligne = t => t
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
               '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(?!\s)([^*\n]+?)(?<!\s)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code>$1</code>');

    for (const ligne of String(md).split('\n')) {
      const brute = ligne.replace(/\s+$/, '');

      if (brute.trim().startsWith('```')) {
        if (dansBloc) sortie.push('</code></pre>');
        else {
          if (dansListe) { sortie.push('</ul>'); dansListe = false; }
          sortie.push('<pre><code>');
        }
        dansBloc = !dansBloc;
        continue;
      }
      if (dansBloc) { sortie.push(echapper(brute)); continue; }

      const nue = echapper(brute.trim());
      if (!nue) { if (dansListe) { sortie.push('</ul>'); dansListe = false; } continue; }

      const puce = nue.match(/^(?:[-*]|\d+\.)\s+(.*)$/);
      if (puce) {
        if (!dansListe) { sortie.push('<ul>'); dansListe = true; }
        sortie.push('<li>' + enligne(puce[1]) + '</li>');
        continue;
      }
      if (dansListe) { sortie.push('</ul>'); dansListe = false; }

      const titre = nue.match(/^(#{1,6})\s+(.*)$/);
      if (titre) {
        const niveau = Math.min(titre[1].length + 1, 6);
        sortie.push(`<h${niveau}>` + enligne(titre[2]) + `</h${niveau}>`);
        continue;
      }
      if (/^-{3,}$/.test(nue)) { sortie.push('<hr>'); continue; }
      sortie.push('<p>' + enligne(nue) + '</p>');
    }

    if (dansListe) sortie.push('</ul>');
    if (dansBloc) sortie.push('</code></pre>');
    return sortie.join('\n');
  }

  const rendu = url => dev[url].html
    + `<div class="pied-dev"><span>Développé le ${(dev[url].genere || '').slice(0, 10)}</span>`
    + ((LOCAL || PUBLIC) ? `<button class="refaire" data-url="${echapper(url)}">refaire</button>` : '')
    + `</div>`;

  // ---- clé du lecteur (site public) ----
  // Elle ne quitte jamais ce navigateur : la page appelle Gemini directement, et il
  // n'existe aucun serveur à qui elle pourrait être envoyée. C'est écrit sur le
  // panneau, parce que personne ne devrait coller une clé sans savoir où elle va.
  const CLE_GEMINI = 'veille-cle-gemini';
  const laCle = () => { try { return localStorage.getItem(CLE_GEMINI) || ''; } catch { return ''; } };
  const boutonCle = document.getElementById('cle');
  const panneauCle = document.getElementById('panneau-cle');

  function rendrePanneauCle(){
    const posee = !!laCle();
    boutonCle.dataset.active = posee;
    boutonCle.textContent = posee ? 'Clé ✓' : 'Clé API';
    panneauCle.innerHTML = `<div class="boite">`
      + `<h2>Développer un article avec votre clé</h2>`
      + `<p>Le bouton <b>Développer</b> de chaque carte demande à Gemini un résumé complet de `
      + `l'article et un exemple d'usage. L'appel part <b>de votre navigateur</b>, avec `
      + `votre clé : elle est enregistrée ici seulement, elle n'est envoyée à aucun `
      + `serveur de ce site, et l'auteur du site ne la voit jamais.</p>`
      + `<p>Une clé gratuite s'obtient sur `
      + `<a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">`
      + `aistudio.google.com/apikey</a>. Les appels sont décomptés de votre quota.</p>`
      + `<div class="rang">`
      + `<input id="saisie-cle" type="password" autocomplete="off" spellcheck="false"`
      + ` placeholder="${posee ? 'Clé enregistrée — en saisir une autre pour la remplacer' : 'AIza…'}">`
      + `<button class="principal" id="poser-cle">Enregistrer</button>`
      + (posee ? `<button id="oublier-cle">Effacer</button>` : '')
      + `</div>`
      + `<p class="note">Rien d'autre n'est conservé : le site est une page statique, `
      + `sans compte, sans traceur et sans base de données.</p>`
      + `</div>`;
  }

  if (PUBLIC) {
    boutonCle.hidden = false;
    rendrePanneauCle();
    boutonCle.addEventListener('click', () => {
      panneauCle.hidden = !panneauCle.hidden;
      if (!panneauCle.hidden) document.getElementById('saisie-cle').focus();
    });
    panneauCle.addEventListener('click', e => {
      if (e.target.id === 'poser-cle') {
        const valeur = document.getElementById('saisie-cle').value.trim();
        if (!valeur) return;
        try { localStorage.setItem(CLE_GEMINI, valeur); } catch (e) {}
        rendrePanneauCle();
        panneauCle.hidden = true;
      }
      if (e.target.id === 'oublier-cle') {
        try { localStorage.removeItem(CLE_GEMINI); } catch (e) {}
        rendrePanneauCle();
      }
    });

    document.getElementById('bandeau').hidden = false;
    document.getElementById('bandeau').innerHTML =
      `Veille quotidienne sur l'IA — collectée, triée et résumée automatiquement. `
      + `Le score de chaque élément mesure son intérêt <b>pour la ligne éditoriale du `
      + `site</b> (Claude et Claude Code d'abord, puis les autres modèles et l'agentic `
      + `coding), et non son importance générale.`;
    // Un seul onglet : la barre n'aurait rien à faire.
    document.getElementById('onglets').hidden = true;
  }

  async function developperAvecCle(url, panneau){
    const cle = laCle();
    if (!cle) {
      // Renvoyer vers un panneau situé en haut de page, à trois écrans de là, c'était
      // faire chercher au lecteur ce qu'on venait de lui refuser. Le champ vient à lui,
      // et l'enregistrement relance le développement dans la foulée.
      panneau.innerHTML = `<p class="attente">Ce bouton demande à Gemini un <b>résumé `
        + `complet en français</b> et un <b>exemple d'usage concret</b>. L'appel part de `
        + `votre navigateur avec votre propre clé : elle reste ici, ce site n'a aucun `
        + `serveur à qui l'envoyer.</p>`
        + `<div class="rang"><input class="cle-ici" type="password" autocomplete="off"`
        + ` spellcheck="false" placeholder="AIza…" aria-label="Clé Gemini">`
        + `<button class="principal poser-ici" data-url="${echapper(url)}">Enregistrer et développer</button></div>`
        + `<p class="note">Clé gratuite sur <a href="https://aistudio.google.com/apikey"`
        + ` target="_blank" rel="noopener">aistudio.google.com/apikey</a>, décomptée de `
        + `votre quota. Rien d'autre n'est conservé.</p>`;
      return;
    }

    const item = itemPour(url);
    if (!item) { panneau.innerHTML = `<p class="attente echec">Article introuvable.</p>`; return; }
    const cible = (item.cible || '').trim() || url;

    // Le navigateur ne peut pas lire un site tiers : c'est le Worker qui va chercher le
    // texte. Sans lui, on développe à partir du titre et de l'extrait — le modèle le
    // sait, les consignes lui demandent de le dire plutôt que de broder.
    let contenu = '';
    if (D.worker) {
      panneau.innerHTML = `<p class="attente">Lecture de l'article…</p>`;
      try {
        const r = await fetch(D.worker + '/?url=' + encodeURIComponent(cible));
        const d = await r.json();
        contenu = d.texte || '';
      } catch (e) { contenu = ''; }
    }

    panneau.innerHTML = `<p class="attente">Rédaction par Gemini…</p>`;
    try {
      const corps = await appelerGemini(cle, promptDeveloppement(item, contenu));
      dev[url] = {html: markdownHtml(corps), genere: new Date().toISOString()};
      memoriserDev();
      panneau.innerHTML = rendu(url);
      marquerFait(url);
    } catch (e) {
      panneau.innerHTML = `<p class="attente echec">Échec : ${echapper(String(e.message || e))}</p>`;
    }
  }

  function promptDeveloppement(item, contenu){
    const lignes = [`Titre : ${item.titre || ''}`, `Source : ${item.source_nom || ''}`];
    if (item.date) lignes.push(`Date : ${item.date}`);
    lignes.push(`URL : ${item.url || ''}`);
    if (item.extrait) lignes.push(`\nExtrait collecté :\n${item.extrait}`);
    lignes.push(`\nContenu de la page :\n${contenu || '(non récupéré)'}`);
    return `Tu produis une veille IA personnelle pour ce profil :\n\n${D.profil}\n\n`
      + `${D.consignes}\n\nVoici l'article :\n\n` + lignes.join('\n');
  }

  async function appelerGemini(cle, prompt){
    const reponse = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${D.modele}:generateContent`,
      {
        method: 'POST',
        headers: {'x-goog-api-key': cle, 'Content-Type': 'application/json'},
        body: JSON.stringify({
          contents: [{parts: [{text: prompt}]}],
          generationConfig: {maxOutputTokens: 12000, temperature: 0.3}
        })
      }
    );
    const donnees = await reponse.json().catch(() => ({}));
    if (!reponse.ok) {
      const message = (donnees.error && donnees.error.message) || ('HTTP ' + reponse.status);
      throw new Error(reponse.status === 400 ? 'clé refusée — ' + message : message);
    }
    const parts = ((donnees.candidates || [])[0] || {}).content;
    const texte = ((parts && parts.parts) || []).map(p => p.text || '').join('').trim();
    if (!texte) throw new Error('réponse vide du modèle');
    return texte;
  }

  const marquerFait = url =>
    document.querySelectorAll(`.developper[data-url="${CSS.escape(url)}"]`)
      .forEach(b => { b.dataset.fait = 'true'; });

  async function developper(bouton, refaire){
    const url = bouton.dataset.url;
    const panneau = bouton.closest('.enveloppe').querySelector('.developpement');

    // Replier n'a de sens que s'il y a quelque chose à replier. Sur un panneau resté en
    // attente ou en échec — clé manquante, appel raté — le clic suivant doit réessayer :
    // c'est ce qu'on fait spontanément après avoir renseigné sa clé.
    if (!refaire && bouton.getAttribute('aria-expanded') === 'true' && dev[url]) {
      panneau.hidden = true;
      bouton.setAttribute('aria-expanded', 'false');
      bouton.textContent = LIBELLE_DEV.fait;
      return;
    }

    panneau.hidden = false;
    bouton.setAttribute('aria-expanded', 'true');
    bouton.textContent = LIBELLE_DEV.ouvert;

    if (dev[url] && !refaire) { panneau.innerHTML = rendu(url); return; }
    if (PUBLIC) return developperAvecCle(url, panneau);
    if (!LOCAL) {
      panneau.innerHTML = `<p class="attente">Ouvrir le site par le raccourci `
        + `<code>ouvrir_site.cmd</code> pour développer un article : la page a besoin `
        + `du serveur local, qui seul détient la clé de l'API.</p>`;
      return;
    }

    const item = itemPour(url);
    if (!item) { panneau.innerHTML = `<p class="attente echec">Article introuvable.</p>`; return; }

    // Lecture de la page puis rédaction : une vingtaine de secondes. Le dire, plutôt
    // que de laisser un panneau vide qui donne l'impression d'un bouton mort.
    panneau.innerHTML = `<p class="attente">Lecture de l'article et rédaction…</p>`;
    try {
      const reponse = await fetch('/api/developper', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({item: item, refaire: !!refaire})
      });
      const donnees = await reponse.json();
      if (!reponse.ok || donnees.erreur) throw new Error(donnees.erreur || reponse.status);
      dev[url] = donnees;
      panneau.innerHTML = rendu(url);
      marquerFait(url);
    } catch (e) {
      panneau.innerHTML = `<p class="attente echec">Échec : ${echapper(String(e.message || e))}`
        + `<br>Détail dans <code>.veille/state/serveur.log</code>.</p>`;
    }
  }

  function basculer(url){
    if (favoris[url]) {
      delete favoris[url];
      retires[url] = new Date().toISOString();
    } else {
      const item = parUrl.get(url);
      if (!item) return;
      favoris[url] = Object.assign({}, item, {favori_le: new Date().toISOString()});
      delete retires[url];
    }
    sauverFavoris();
    rendreOnglets();
    // Hors de l'onglet Favoris, un rendu complet replierait les signets ouverts et
    // ramènerait la page en haut. On ne retouche donc que le bouton concerné.
    if (vue === 'favoris') { rendreSujets(); rendre(); return; }
    flux.querySelectorAll(`.etoile[data-url="${CSS.escape(url)}"]`).forEach(b => {
      const marque = !!favoris[url];
      b.setAttribute('aria-pressed', marque);
      b.title = b.ariaLabel = marque ? 'Retirer des favoris' : 'Mettre en favori';
      b.textContent = marque ? '★' : '☆';
    });
  }

  flux.addEventListener('click', e => {
    const bouton = e.target.closest('.etoile');
    if (bouton) { e.preventDefault(); basculer(bouton.dataset.url); return; }
    const plus = e.target.closest('.developper');
    if (plus) { e.preventDefault(); developper(plus, false); return; }
    const ancreBt = e.target.closest('.lien-ancre');
    if (ancreBt) {
      e.preventDefault();
      const adresse = location.origin + location.pathname + '#' + ancreBt.dataset.ancre;
      const dit = mot => { ancreBt.textContent = mot;
        setTimeout(() => { ancreBt.textContent = 'Lien'; }, 1800); };
      // `navigator.clipboard` n'existe pas sur une page ouverte en file:// : le repli
      // affiche l'adresse dans une invite, d'où elle se copie à la main.
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(adresse).then(() => dit('Copié'), () => prompt('Lien', adresse));
      } else {
        prompt('Lien vers cet élément', adresse);
      }
      return;
    }
    const poser = e.target.closest('.poser-ici');
    if (poser) {
      e.preventDefault();
      const champCle = poser.closest('.rang').querySelector('.cle-ici');
      const valeur = champCle.value.trim();
      if (!valeur) return champCle.focus();
      try { localStorage.setItem(CLE_GEMINI, valeur); } catch (err) {}
      rendrePanneauCle();
      developper(poser.closest('.enveloppe').querySelector('.developper'), true);
      return;
    }
    const refaire = e.target.closest('.refaire');
    if (refaire) {
      e.preventDefault();
      developper(refaire.closest('.enveloppe').querySelector('.developper'), true);
      return;
    }
    const carte = e.target.closest('.item');
    if (!carte) return;
    // Déplier un signet n'est pas le lire : on ne l'estompe qu'une fois parti vers la
    // ressource. Sinon le contenu qu'on vient d'ouvrir s'afficherait grisé.
    if (carte.classList.contains('signet') && !e.target.closest('a')) return;
    marquer(carte.dataset.url);
    carte.classList.add('lu');
  });

  // La page est un fichier local : elle ne peut rien écrire dans le vault. Elle produit
  // donc un fichier de téléchargement, que la synchronisation suivante ramasse — même
  // circuit que l'export des signets. Les retraits partent avec, sans quoi l'import
  // ressusciterait ce qui vient d'être enlevé.
  boutonSauver.addEventListener('click', () => {
    const charge = {
      genere: new Date().toISOString(),
      favoris: listeFavoris(),
      retires: retires
    };
    const blob = new Blob([JSON.stringify(charge, null, 1)], {type: 'application/json'});
    const lien = document.createElement('a');
    lien.href = URL.createObjectURL(blob);
    lien.download = 'favoris-' + new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-') + '.json';
    document.body.appendChild(lien);
    lien.click();
    lien.remove();
    setTimeout(() => URL.revokeObjectURL(lien.href), 5000);

    boutonSauver.textContent = 'Sauvegardé ✓';
    setTimeout(() => { boutonSauver.textContent = 'Sauvegarder'; }, 2500);
  });

  // Des favoris ont pu être posés pendant que le serveur ne tournait pas : ils partent
  // au premier chargement servi, sans rien demander.
  if (LOCAL) {
    boutonSauver.hidden = true;
    if (listeFavoris().length || Object.keys(retires).length) versLeVault();
  }

  // ---- bandeau de reprise ----
  // Il ne dépend ni de la voie ni du jour affiché : il parle de toute l'archive, et
  // ne bouge pas pendant la visite. Il est donc rendu une fois, au démarrage.
  function rendreReprise(){
    const bloc = document.getElementById('reprise');
    if (isNaN(seuilVisite)) return;                    // première visite

    const neufs = D.jours.flatMap(j => j.items).filter(i => !estSignet(i) && estNouveau(i));
    if (!neufs.length) return;

    const essentiels = neufs.filter(i => i.voie === 'essentiel').length;
    // Le plus ancien jour qui porte du neuf, et non le plus récent : on reprend là
    // où on s'est arrêté, sans laisser un trou derrière soi. D.jours va du plus
    // récent au plus ancien, d'où le dernier de la liste et non le premier.
    const avecNeuf = D.jours.filter(j => j.items.some(i => !estSignet(i) && estNouveau(i)));
    const jour = avecNeuf[avecNeuf.length - 1];
    bloc.innerHTML =
      `<span><b>${neufs.length} nouveauté${neufs.length > 1 ? 's' : ''}</b> `
      + `depuis votre dernière visite, ${depuis(Date.now() - seuilVisite)}`
      + (essentiels ? ` — dont ${essentiels} essentielle${essentiels > 1 ? 's' : ''}` : '')
      + `.</span>`
      + `<button id="reprendre" data-date="${jour ? jour.date : ''}">Reprendre ↓</button>`;
    bloc.hidden = false;
  }

  rendreReprise();

  document.getElementById('reprise').addEventListener('click', e => {
    if (!e.target.closest('#reprendre')) return;
    const date = e.target.closest('#reprendre').dataset.date;
    if (date && PAR_DATE.has(date)) allerA(date);
    flux.scrollIntoView({block: 'start', behavior: 'smooth'});
  });

  // La barre d'état ne dépend d'aucun filtre : elle dit quand la page a été fabriquée
  // et ce qu'elle contient, une fois pour toutes.
  document.getElementById('resume').textContent =
    `Maj ${D.genere} · ${D.jours.length} jour${D.jours.length > 1 ? 's' : ''} d'archive`;

  rendre();

  // Un lien reçu pointe vers un élément, pas vers une journée : il faut d'abord
  // retrouver le jour qui le porte, sans quoi l'ancre viserait un noeud absent du
  // document. Le surlignage dit lequel des quarante on est venu voir.
  function allerAncre(){
    const cible = location.hash.slice(1);
    if (!cible) return;
    const jour = D.jours.find(j => j.items.some(i => ancre(i.url) === cible));
    if (jour && jour.date !== jourActif) allerA(jour.date);

    // L'élément visé peut être filtré par la voie en cours — un lien vers un item
    // classé « bruit » n'afficherait rien. On élargit alors la voie plutôt que de
    // laisser la page muette devant un lien qu'on vient de suivre.
    if (!document.getElementById(cible) && voie !== 'tout') {
      voie = 'tout';
      rendreVoies(); rendreSujets(); rendre();
    }
    const noeud = document.getElementById(cible);
    if (!noeud) return;
    noeud.scrollIntoView({block: 'center'});
    noeud.classList.add('vise');
    setTimeout(() => noeud.classList.remove('vise'), 2600);
  }

  allerAncre();
  window.addEventListener('hashchange', allerAncre);
})();
