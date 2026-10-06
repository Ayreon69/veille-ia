(function(){
  const D = JSON.parse(document.getElementById('donnees').textContent);
  const flux = document.getElementById('flux');
  const champ = document.getElementById('recherche');
  const barre = document.getElementById('filtres');
  const barreVoies = document.getElementById('voies');
  const boutonSauver = document.getElementById('sauver');
  const etat = document.getElementById('etat');

  // Les changements de journée et de vue passent par l'API View Transitions quand le
  // navigateur la connaît : l'ancienne liste glisse dans le sens du temps, la nouvelle
  // arrive. Sans elle, ou si le système demande moins d'animations, la mise à jour est
  // immédiate — l'animation n'est jamais une condition du fonctionnement.
  const sobre = matchMedia('(prefers-reduced-motion: reduce)');
  function transition(sens, maj){
    // Une liste de toutes les journées dépasse 200 000 px : en faire un instantané pour
    // l'animer coûterait plus que l'animation n'apporte.
    const enorme = flux.offsetHeight > 30000;
    if (!document.startViewTransition || sobre.matches || document.hidden || enorme) return maj();
    document.documentElement.dataset.sens = sens;
    const t = document.startViewTransition(maj);
    t.finished.finally(() => { delete document.documentElement.dataset.sens; });
  }

  // Les articles déjà ouverts sont estompés : sur plusieurs jours d'archive, c'est
  // ce qui distingue le nouveau du déjà-vu.
  const CLE = 'veille-lus';
  let lus = new Set();
  try { lus = new Set(JSON.parse(localStorage.getItem(CLE) || '[]')); } catch (e) {}
  const ecrireLus = () => {
    try { localStorage.setItem(CLE, JSON.stringify([...lus].slice(-4000))); } catch (e) {}
  };
  const marquer = url => { lus.add(url); ecrireLus(); };
  const demarquer = url => { lus.delete(url); ecrireLus(); };

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
    agregateur:'Agrégateurs', analyse:'Analyses', x:'Sur X', francophone:'Francophone',
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

  // Tendances ne lit que ce que la page publique porte déjà : elle y a sa place. La
  // semaine aussi, depuis le 06/10 : signets et favoris restent seuls hors ligne.
  const VUES = D.public
    ? {veille:'Veille', semaine:'Semaine', tendances:'Tendances'}
    : {veille:'Veille', semaine:'Semaine', tendances:'Tendances', signets:'Signets', favoris:'Favoris'};
  // Les icônes ne s'affichent que dans la barre d'onglets du bas, sur téléphone : à
  // cette largeur, un nom seul se lit mal sous le pouce. Tracés au trait, 24 unités.
  const trace = d => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"`
    + ` stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
  const ICONES = {
    veille: trace('<path d="M4 5h16M4 10h16M4 15h10M4 20h7"/>'),
    semaine: trace('<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4M7.5 14h3M13.5 14h3"/>'),
    tendances: trace('<path d="M3.5 19.5h17"/><path d="M5 15l4.5-5 3.5 3 6-7"/><path d="M15 6h4v4"/>'),
    signets: trace('<path d="M7 3.5h10a1 1 0 0 1 1 1v16l-6-4-6 4v-16a1 1 0 0 1 1-1z"/>'),
    favoris: trace('<path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.8L12 16.8l-5.2 2.8 1-5.8-4.3-4.1 5.9-.8z"/>'),
  };
  const estSignet = i => i.categorie === 'signets';

  // Masquer les lus fait de la journée une liste qui se vide à mesure qu'on la lit.
  // Le choix est retenu d'une visite à l'autre, dans ce navigateur seulement.
  let masquerLus = false;
  try { masquerLus = localStorage.getItem('veille-masquer-lus') === '1'; } catch (e) {}

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
  //
  // La recherche ignore les accents et la casse, et chaque mot est cherché pour
  // lui-même : « resume claude » trouve « Claude … résumé », là où l'ancienne
  // recherche exigeait la phrase exacte, accents compris. Le texte replié de chaque
  // élément est calculé une fois : la page compte huit fois par frappe.
  const plier = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  let termes = [];
  const replie = new WeakMap();
  const texteDe = i => {
    let t = replie.get(i);
    if (t === undefined) {
      t = plier([i.titre, i.source_nom, i.extrait, i.phrase, i.analyse, i.justification].join(' '));
      replie.set(i, t);
    }
    return t;
  };
  const texteOk = i => !termes.length || termes.every(m => texteDe(i).includes(m));

  // Le surlignage travaille sur le texte brut, avant échappement : chercher dans du
  // HTML échappé aurait surligné « amp » au milieu d'un &amp;. Chaque lettre admet
  // ses variantes accentuées, pour surligner « résumé » quand on a tapé « resume ».
  const VARIANTES = {a:'aàâä', c:'cç', e:'eéèêë', i:'iîï', o:'oôö', u:'uùûü', y:'yÿ'};
  let motif = null;
  const construireMotif = () => {
    motif = termes.length ? new RegExp('(' + termes.map(m => [...m].map(c =>
      VARIANTES[c] ? `[${VARIANTES[c]}]` : c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join(''))
      .sort((a, b) => b.length - a.length).join('|') + ')', 'gi') : null;
  };
  const surligner = s => {
    const brut = String(s || '');
    if (!motif) return echapper(brut);
    return brut.split(motif).map((morceau, k) =>
      k % 2 ? `<mark>${echapper(morceau)}</mark>` : echapper(morceau)).join('');
  };

  const tous = D.jours.flatMap(j => j.items);
  const parUrl = new Map(tous.map(i => [i.url, i]));
  // Les favoris ne sont pas un sous-ensemble de la page : certains n'y sont plus.
  // Le lot suit la journée affichée, sans quoi les compteurs des filtres annonceraient
  // l'archive entière au-dessus d'une liste qui ne montre qu'un jour.
  // Les lus masqués sortent du lot lui-même, et donc des compteurs : la règle vaut
  // toujours, un nombre décrit la liste qu'il surplombe.
  const lot = () => (vue === 'favoris'
    ? listeFavoris()
    : joursAffiches().flatMap(j => j.items)
        .filter(i => estSignet(i) === (vue === 'signets'))
        .filter(i => !(masquerLus && vue === 'veille' && lus.has(i.url)))
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
      // Tendances n'est pas une collection : un nombre n'y compterait rien.
      const n = c === 'tendances' ? null
        : c === 'favoris' ? listeFavoris().length
        : c === 'semaine' ? SEMAINES.length
        : tous.filter(i => estSignet(i) === (c === 'signets')).length;
      return `<button class="onglet" role="tab" data-vue="${c}" aria-selected="${c === vue}">`
        + `${ICONES[c] || ''}<span>${nom}</span>`
        + (n === null ? '' : `<span class="n">${n}</span>`) + `</button>`;
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

  // Changer de vue, que ce soit par l'onglet, le clavier ou un renvoi d'une autre vue.
  function changerVue(nouvelle, apres){
    if (!VUES[nouvelle]) return;
    transition('', () => {
      vue = nouvelle;
      curseur = -1;
      if (VOIX) speechSynthesis.cancel();
      // La voie disparaît hors de la veille, et pour la même raison dans les deux
      // cas : un signet comme un favori sont des choix que j'ai faits moi-même, ce
      // n'est pas au score de décider de les masquer. Le sujet, lui, reste utile dans
      // les favoris, qui mélangent actualités et signets ; il n'en a aucun dans
      // l'onglet signets, où tout est de la même catégorie.
      const veille = vue === 'veille';
      // Filtrer ou trier une synthèse rédigée, ou des tendances, n'a aucun sens : les
      // contrôles disparaissent au lieu de rester là sans effet.
      const lecture = vue === 'semaine' || vue === 'tendances';
      barreVoies.hidden = !veille;
      barre.hidden = vue === 'signets' || lecture;
      champ.hidden = lecture;
      selecteurTri.hidden = lecture;
      boutonSauver.hidden = (LOCAL && !envoiKO) || vue !== 'favoris';
      if (!veille) { voie = 'tout'; filtre = 'tout'; }
      else if (voie === 'tout' && D.notes) voie = 'utile';
      rendreOnglets();
      if (apres) apres();
      else { rendreVoies(); rendreSujets(); rendre(); window.scrollTo(0, 0); }
    });
  }

  onglets.addEventListener('click', e => {
    const b = e.target.closest('.onglet');
    if (b && b.dataset.vue !== vue) changerVue(b.dataset.vue);
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
    requete = champ.value.trim();
    termes = plier(requete).split(/\s+/).filter(Boolean);
    construireMotif();
    curseur = -1;
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
      + `<span class="t">${surligner(i.titre)}</span>`
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
      + `<h3>${surligner(i.titre)}</h3>`
      + `<div class="ligne"><span class="src">${echapper(i.source_nom)}</span>`
      + (estNouveau(i) ? `<span class="neuf">nouveau</span>` : '')
      + (h ? `<span>${h}</span>` : '')
      + (i.categorie && !estSignet(i) ? `<span class="cat">${echapper(LIBELLES[i.categorie] || i.categorie)}</span>` : '')
      // Inutile dans l'onglet signets : tout y est un tweet, la mention n'informe plus.
      + (i.titre_utilisateur && !estSignet(i) ? `<span class="avis" title="Titre rédigé par un utilisateur : affirmation, pas fait vérifié">titre d'utilisateur</span>` : '')
      // Une phrase du digest n'est pas un extrait : l'une est écrite par le modèle,
      // l'autre est le texte du site source. Les afficher pareil sans le dire serait
      // faire passer l'un pour l'autre — d'où le marqueur, discret mais présent.
      + (i.phrase ? `<span class="avis" title="Phrase du digest du jour, écrite par le modèle — et non le texte du site source">résumé</span>` : '')
      // La même annonce relayée ailleurs : une ligne, et les autres sources nommées.
      // Rien n'est caché, la liste cesse seulement de se répéter.
      + ((i.aussi && i.aussi.length)
        ? `<span class="aussi">aussi : ${echapper(i.aussi.join(', '))}</span>` : '')
      + `</div>`
      + (i.phrase || i.extrait
        ? `<p class="extrait">${surligner(i.phrase || i.extrait)}</p>`
        : '')
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
    curseur = -1;
    dernierLot = null;
    if (VOIX) speechSynthesis.cancel();
    fermerCalendrier();
    // Les nombres des deux rangées de filtres viennent de changer avec la journée.
    rendreVoies(); rendreSujets(); rendre();
    window.scrollTo(0, 0);
  };

  // Le sens du glissement suit le temps : reculer d'un jour pousse la liste vers la
  // droite, comme une page qu'on tourne vers le passé.
  const allerAvecSens = date => {
    if (date === jourActif) return fermerCalendrier();
    const sens = (jourActif && date && date < jourActif) ? 'passe' : 'futur';
    transition(sens, () => allerA(date));
  };

  const decaler = n => {
    const i = DATES.indexOf(jourActif) + n;
    if (i >= 0 && i < DATES.length) allerAvecSens(DATES[i]);
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

    // Chaque journée est teintée selon ce qu'elle a porté d'essentiel, rapporté à la
    // plus riche du mois : le calendrier se lit comme une carte de chaleur, et l'on
    // voit d'un coup d'œil quelle journée mérite qu'on y retourne.
    const essentielsDe = j => j.items.filter(i => !estSignet(i) && i.voie === 'essentiel').length;
    const duMois = DATES.filter(d => d.startsWith(courant)).map(d => essentielsDe(PAR_DATE.get(d)));
    const plafond = Math.max(1, ...duMois);

    let cases = '';
    for (let k = 0; k < decalage; k++) cases += `<span class="cal-case"></span>`;
    for (let d = 1; d <= nb; d++) {
      const cle = cleDate(an, mois, d);
      const j = PAR_DATE.get(cle);
      const ess = j ? essentielsDe(j) : 0;
      cases += j
        ? `<button class="cal-case plein" data-date="${cle}" style="--chaleur:${(ess / plafond).toFixed(2)}"`
          + ` title="${ess} essentiel${ess > 1 ? 's' : ''}"`
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
    // Pas de transition vers l'empilement complet : voir transition().
    const cible = jourActif === null ? (dernierJour || DATES[0] || null) : null;
    if (cible === null) allerA(null); else transition('', () => allerA(cible));
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
    if (case_) allerAvecSens(case_.dataset.date);
  });

  document.addEventListener('click', e => {
    if (!calendrier.hidden && !(e.target instanceof Element && e.target.closest('.nav-jour')))
      fermerCalendrier();
  });

  // ---- clavier ----
  // Une journée se trie comme une boîte de réception : j et k passent d'un élément à
  // l'autre, et une lettre agit sur celui qu'on a choisi. Le curseur n'est qu'une
  // position dans la liste affichée ; il repart de zéro à chaque nouvelle liste.
  let curseur = -1;
  const enveloppes = () => [...flux.querySelectorAll('.enveloppe')];
  const choisir = n => {
    const liste = enveloppes();
    if (!liste.length) return;
    curseur = Math.max(0, Math.min(liste.length - 1, n));
    liste.forEach((el, k) => el.classList.toggle('curseur', k === curseur));
    liste[curseur].scrollIntoView({block: 'nearest', behavior: sobre.matches ? 'auto' : 'smooth'});
  };
  const choisi = () => (curseur >= 0 ? enveloppes()[curseur] : null) || null;

  function agirSur(el, touche){
    const url = (el.querySelector('[data-url]') || {}).dataset?.url;
    if (touche === 'o' || touche === 'Enter') {
      const lien = el.querySelector('a.item');
      if (lien) return lien.click();       // passe par le même chemin qu'un clic : marqué lu
      const signet = el.querySelector('details.signet');
      if (signet) signet.open = !signet.open;
      return;
    }
    if (touche === 'd') return el.querySelector('.developper')?.click();
    if (touche === 's') return el.querySelector('.etoile')?.click();
    if (touche === 'c') return el.querySelector('.lien-ancre')?.click();
    if (touche === 'm' && url) {
      if (lus.has(url)) demarquer(url); else marquer(url);
      el.querySelector('.item')?.classList.toggle('lu', lus.has(url));
      rendreLecture();
    }
  }

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !calendrier.hidden) return fermerCalendrier();
    // Les touches appartiennent au champ de saisie tant qu'on y écrit ; Échap l'en fait
    // sortir. `closest` n'existe que sur un Element : la cible peut être le document.
    if (e.target instanceof Element && e.target.closest('input, select, textarea')) {
      if (e.key === 'Escape' && e.target === champ) champ.blur();
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey || aide.open) return;
    const k = e.key;

    if (k === '?') { e.preventDefault(); return aide.showModal(); }
    if (k === '/' && !champ.hidden) { e.preventDefault(); champ.focus(); return champ.select(); }
    if (/^[1-9]$/.test(k)) {
      const cible = Object.keys(VUES)[Number(k) - 1];
      if (cible && cible !== vue) changerVue(cible);
      return;
    }
    if (k === 't' && vue === 'veille' && DATES.length && jourActif !== DATES[0]) {
      return allerAvecSens(DATES[0]);
    }
    if (k === 'j' || k === 'k') {
      e.preventDefault();
      return choisir(curseur < 0 ? 0 : curseur + (k === 'j' ? 1 : -1));
    }
    // Entrée n'est à nous que si rien n'a le focus : sur un bouton, elle l'active.
    const el = choisi();
    if (el && 'odscm'.includes(k) || (el && k === 'Enter' && e.target === document.body)) {
      e.preventDefault();
      return agirSur(el, k);
    }

    if (k !== 'ArrowLeft' && k !== 'ArrowRight') return;
    const recule = k === 'ArrowLeft';
    if (vue === 'semaine') {
      e.preventDefault();
      return allerASemaine(semaineActive + (recule ? 1 : -1));
    }
    if (vue !== 'veille' || surToutLArchive()) return;
    e.preventDefault();
    decaler(recule ? 1 : -1);
  });

  // ---- balayage, sur écran tactile ----
  // Le geste d'un téléphone pour « page suivante ». Un balayage franchement
  // horizontal seulement : un défilement légèrement penché ne doit pas changer de
  // jour, ni un glissement dans une rangée de filtres ou un bloc de code.
  let toucher = null;
  flux.addEventListener('touchstart', e => {
    const t = e.touches[0];
    toucher = (e.touches.length === 1 && !e.target.closest('pre, .defile, .rythme, .pistes'))
      ? {x: t.clientX, y: t.clientY, quand: Date.now()} : null;
  }, {passive: true});
  flux.addEventListener('touchend', e => {
    if (!toucher) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - toucher.x, dy = t.clientY - toucher.y;
    const vif = Date.now() - toucher.quand < 600;
    toucher = null;
    if (!vif || Math.abs(dx) < 70 || Math.abs(dy) > Math.abs(dx) * 0.5) return;
    const recule = dx > 0;       // le doigt part vers la droite : on remonte le temps
    if (vue === 'semaine') return allerASemaine(semaineActive + (recule ? 1 : -1));
    if (vue === 'veille' && !surToutLArchive()) decaler(recule ? 1 : -1);
  }, {passive: true});

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
    if (i < 0 || i >= SEMAINES.length || i === semaineActive) return fermerListeSemaines();
    // Les semaines sont rangées de la plus récente à la plus ancienne : un indice
    // plus grand remonte le temps.
    transition(i > semaineActive ? 'passe' : 'futur', () => {
      semaineActive = i;
      fermerListeSemaines();
      rendre();
      window.scrollTo(0, 0);
    });
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
  // Les colonnes de la semaine et du rythme des Tendances font de même.
  flux.addEventListener('click', e => {
    const b = e.target instanceof Element && e.target.closest('.lien-jour, .jour-barre, .r-jour');
    if (!b || b.disabled || !PAR_DATE.has(b.dataset.date)) return;
    changerVue('veille', () => allerA(b.dataset.date));
  });

  // Les dates d'un intervalle, du premier au dernier jour inclus, en AAAA-MM-JJ.
  const joursEntre = (debut, fin) => {
    const sortie = [];
    const [a, m, j] = debut.split('-').map(Number);
    for (let d = new Date(a, m - 1, j); ; d.setDate(d.getDate() + 1)) {
      const cle = cleDate(d.getFullYear(), d.getMonth(), d.getDate());
      if (cle > fin || sortie.length > 400) break;
      sortie.push(cle);
    }
    return sortie;
  };

  // Le poids d'une journée, par voie. Les signets n'en font pas partie : ils ne sont
  // pas une production du jour, mais un relevé de mes propres choix.
  const bilan = j => {
    const items = j ? j.items.filter(i => !estSignet(i)) : [];
    const ess = items.filter(i => i.voie === 'essentiel').length;
    const bruit = items.filter(i => i.voie === 'bruit').length;
    return {total: items.length, ess, utile: items.length - ess - bruit, bruit, items};
  };

  // ---- la semaine d'un coup d'œil ----
  // Sept colonnes au-dessus de la synthèse : ce que chaque journée a pesé et ce qu'elle
  // a porté d'essentiel. Un jour sans édition — un run tombé — se voit comme un trou,
  // au lieu de passer pour une journée calme.
  function coupDOeil(s){
    if (!s.debut || !s.fin) return '';
    const jours = joursEntre(s.debut, s.fin).map(d => ({date: d, b: bilan(PAR_DATE.get(d)), la: PAR_DATE.has(d)}));
    const max = Math.max(1, ...jours.map(x => x.b.ess + x.b.utile));
    const noms = ['lun', 'mar', 'mer', 'jeu', 'ven', 'sam', 'dim'];
    const somme = cle => jours.reduce((n, x) => n + x.b[cle], 0);
    const versions = jours.flatMap(x => x.b.items.filter(i => i.version));
    const manquants = jours.filter(x => !x.la).length;
    return `<div class="coup-doeil" role="group" aria-label="La semaine jour par jour">`
      + jours.map((x, k) => {
        const h = v => `${(v / max * 100).toFixed(1)}%`;
        const titre = x.la
          ? `${libelleCourt(x.date)} — ${x.b.ess + x.b.utile} éléments, dont ${x.b.ess} essentiel${x.b.ess > 1 ? 's' : ''}`
          : `${libelleCourt(x.date)} — pas d'édition ce jour-là`;
        return `<button class="jour-barre" data-date="${x.date}" title="${titre}"${x.la ? '' : ' disabled'}>`
          + `<span class="jb-colonne">`
          + (x.b.ess ? `<i class="jb-ess" style="height:${h(x.b.ess)}"></i>` : '')
          + (x.b.utile ? `<i class="jb-utile" style="height:${h(x.b.utile)}"></i>` : '')
          + `</span><span class="jb-nom">${noms[k]}</span>`
          + `<span class="jb-n">${x.la ? x.b.ess + x.b.utile : '—'}</span></button>`;
      }).join('')
      + `</div><p class="legende">`
      + `<span><span class="pastille ess"></span><b>${somme('ess')}</b> essentiels</span>`
      + `<span><span class="pastille utile"></span><b>${somme('utile')}</b> utiles</span>`
      + (versions.length ? `<span><b>${versions.length}</b> version${versions.length > 1 ? 's' : ''} publiée${versions.length > 1 ? 's' : ''}</span>` : '')
      + (manquants ? `<span>${manquants} jour${manquants > 1 ? 's' : ''} sans édition</span>` : '')
      + `</p>`;
  }

  // « mardi 22 sept. » : assez pour se repérer dans une infobulle ou une légende.
  const libelleCourt = date => {
    const [a, m, j] = date.split('-').map(Number);
    return new Date(a, m - 1, j).toLocaleDateString('fr-FR', {weekday: 'long', day: 'numeric', month: 'short'});
  };

  function rendreSemaine(){
    if (!SEMAINES.length) {
      flux.innerHTML = `<p class="vide">${DESSIN_VIDE}Aucun digest hebdomadaire pour l'instant.<br><br>`
        + `Le premier est écrit le lundi matin qui suit une semaine complète, `
        + `ou à la demande avec <code>python .veille/run_weekly.py</code>.</p>`;
      return resumer(0, 'rien à lire', 'semaine');
    }
    const s = SEMAINES[semaineActive];
    flux.innerHTML = `<section class="jour hebdo">${coupDOeil(s)}<div class="corps">${s.html}</div></section>`;
    // Une journée sortie de la fenêtre d'affichage n'est plus atteignable : le renvoi
    // reste lisible, mais cesse d'être un bouton qui ne mènerait nulle part.
    flux.querySelectorAll('.lien-jour').forEach(b => {
      if (!PAR_DATE.has(b.dataset.date)) b.disabled = true;
    });
    resumer(SEMAINES.length, s.libelle, 'semaine');
  }

  // ---- rail ----
  // « Quelles versions sont sorties » est une question distincte de « qu'est-ce qui
  // s'est écrit » : pour qui suit Claude Code ou MCP, c'est même la première. Noyée
  // dans un flux trié par score, elle n'avait pas de réponse à un coup d'œil.
  const rail = document.getElementById('rail');

  function rendreRail(){
    // Le rail décrit la journée affichée, pas la sélection en cours : il reste stable
    // quand on change de voie ou de sujet, sinon il perdrait son rôle de repère.
    const jours = joursAffiches();
    const items = jours.flatMap(j => j.items).filter(i => !estSignet(i));
    // Pendant une recherche, il n'y a plus de journée à décrire : les versions de
    // tout l'archive, sans rapport avec le mot cherché, ne seraient que du bruit.
    if (vue !== 'veille' || requete || !items.length) { rail.hidden = true; return; }

    const versions = items.filter(i => i.version).slice(0, 8);
    const sources = [...items.reduce((m, i) => m.set(i.source_nom, (m.get(i.source_nom) || 0) + 1), new Map())]
      .sort((a, b) => b[1] - a[1]);

    rail.innerHTML =
      (versions.length
        ? `<section class="bloc-versions"><h2>Versions publiées</h2><ul class="versions">`
          + versions.map(i =>
              `<li><a href="#${ancre(i.url)}"><span class="v-source">${echapper(i.source_nom.replace(' (releases)', ''))}</span>`
              + `<span class="v-num">${echapper(i.titre)}</span></a></li>`).join('')
          + `</ul></section>`
        : '')
      + `<section class="bloc-sources"><h2>Sources du jour</h2><ul class="sources">`
      + sources.map(([nom, n]) =>
          `<li><span>${echapper(nom)}</span><b>${n}</b></li>`).join('')
      + `</ul><button class="bt-texte vers-tendances">Ce que rapporte chaque source →</button></section>`;
    rail.hidden = false;
  }

  // Le compte du jour ne dit pas ce qu'une source vaut sur la durée : l'onglet
  // Tendances, si. Le rail y renvoie, à la section qui en parle.
  rail.addEventListener('click', e => {
    if (!(e.target instanceof Element && e.target.closest('.vers-tendances'))) return;
    changerVue('tendances', () => {
      rendreVoies(); rendreSujets(); rendre();
      const cible = [...flux.querySelectorAll('.t-titre')].find(h => /source/i.test(h.textContent));
      if (cible) cible.scrollIntoView({block: 'start'});
    });
  });

  // La marque du site, au repos, au-dessus des pages vides : un radar qui n'a rien vu.
  const DESSIN_VIDE = `<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">`
    + `<circle cx="32" cy="32" r="26"/><circle cx="32" cy="32" r="16" stroke-dasharray="2 4"/>`
    + `<path d="M32 32V6" stroke-linecap="round"/><circle cx="32" cy="32" r="3" fill="currentColor"/></svg>`;

  // ---- thème ----
  // Trois états, dans l'ordre où on les parcourt : celui du système, clair, sombre.
  // Le choix est posé sur <html> avant même la feuille de style (voir page.html).
  const boutonTheme = document.getElementById('theme');
  const ICONES_THEME = {
    auto: trace('<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor"/>'),
    light: trace('<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>'),
    dark: trace('<path d="M19.5 14.5A8 8 0 0 1 9.5 4.5a8 8 0 1 0 10 10z"/>'),
  };
  const NOMS_THEME = {auto: 'Thème du système', light: 'Thème clair', dark: 'Thème sombre'};
  const themeCourant = () => document.documentElement.dataset.theme || 'auto';
  const COULEURS_BARRE = {light: '#f8f6f1', dark: '#0b0a0f'};
  function rendreTheme(){
    const t = themeCourant();
    // Un thème choisi à la main vaut pour les deux réglages du système.
    document.querySelectorAll('meta[name="theme-color"]').forEach(m => {
      const systeme = m.media.includes('dark') ? 'dark' : 'light';
      m.content = COULEURS_BARRE[t === 'auto' ? systeme : t];
    });
    boutonTheme.innerHTML = ICONES_THEME[t];
    boutonTheme.title = `${NOMS_THEME[t]} — cliquer pour changer`;
    boutonTheme.setAttribute('aria-label', `${NOMS_THEME[t]}. Changer de thème`);
  }
  boutonTheme.addEventListener('click', () => {
    const suite = {auto: 'light', light: 'dark', dark: 'auto'}[themeCourant()];
    transition('', () => {
      if (suite === 'auto') delete document.documentElement.dataset.theme;
      else document.documentElement.dataset.theme = suite;
      rendreTheme();
    });
    try {
      if (suite === 'auto') localStorage.removeItem('veille-theme');
      else localStorage.setItem('veille-theme', suite);
    } catch (e) {}
  });
  rendreTheme();

  // ---- aide clavier ----
  const aide = document.getElementById('aide');
  document.getElementById('aide-bt').addEventListener('click', () => aide.showModal());
  // L'aide ne décrit que ce que la page offre : pas de favoris sur le site public.
  document.getElementById('nb-onglets').textContent = Object.keys(VUES).length;
  if (PUBLIC) aide.querySelectorAll('.prive').forEach(n => n.remove());
  // Un clic sur le fond, hors de la boîte, la referme.
  aide.addEventListener('click', e => { if (e.target === aide) aide.close(); });

  // ---- onglet Tendances ------------------------------------------------------
  // Ce que la lecture jour après jour ne montre pas : le rythme de l'actualité, les
  // sujets qui prennent de la place, la cadence des versions, et ce que rapporte
  // chaque source. Tout se calcule ici, à partir des journées que la page porte déjà.
  const nf = new Intl.NumberFormat('fr-FR');
  const lissage = (v, r = 1) => v.map((_, k) => {
    const f = v.slice(Math.max(0, k - r), k + r + 1);
    return f.reduce((a, b) => a + b, 0) / f.length;
  });

  // Une courbe de quatre semaines, dessinée au trait. La zone teintée à droite est la
  // dernière semaine — celle qu'on compare au reste.
  function courbe(valeurs, {l = 96, h = 26, recents = 0} = {}){
    const max = Math.max(1e-9, ...valeurs);
    const pas = valeurs.length > 1 ? l / (valeurs.length - 1) : l;
    const pts = valeurs.map((v, k) => [k * pas, h - 2 - (v / max) * (h - 5)]);
    const d = pts.map((p, k) => (k ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join('');
    const zone = recents
      ? `<rect class="recent" x="${(l - pas * (recents - 0.5)).toFixed(1)}" y="0" width="${(pas * (recents - 0.5)).toFixed(1)}" height="${h}"/>` : '';
    const fin = pts[pts.length - 1];
    return `<svg class="spark" viewBox="0 0 ${l} ${h}" aria-hidden="true">${zone}`
      + `<path class="aire" d="${d}L${l} ${h}L0 ${h}Z"/><path class="ligne-s" d="${d}"/>`
      + `<circle class="fin" cx="${fin[0].toFixed(1)}" cy="${fin[1].toFixed(1)}" r="2.2"/></svg>`;
  }

  // Les repères de mois sous un axe de dates. `bornes` : les points sont-ils posés aux
  // extrémités (une piste) ou au début de chaque colonne (un histogramme) ?
  function axeMois(dates, bornes){
    const n = bornes ? Math.max(1, dates.length - 1) : dates.length;
    const debutMois = dates.map((d, k) => d.endsWith('-01') ? k : -1).filter(k => k > 0);
    const place = k => `left:${(k / n * 100).toFixed(2)}%`;
    const date = (d, opts) => {
      const [a, m, j] = d.split('-').map(Number);
      return new Date(a, m - 1, j).toLocaleDateString('fr-FR', opts);
    };
    // Le premier jour n'a d'étiquette que s'il laisse la place au premier mois entier.
    const premier = (!debutMois.length || debutMois[0] > dates.length * 0.14)
      ? `<span style="${place(0)}">${date(dates[0], {day: 'numeric', month: 'short'})}</span>` : '';
    return premier + debutMois.map(k => `<span style="${place(k)}">${date(dates[k], {month: 'long'})}</span>`).join('');
  }

  // Les mots vides, en anglais et en français, et ceux qui ne disent rien dans une
  // veille sur l'IA parce qu'ils sont partout : « model », « release », « ai ».
  const MOTS_VIDES = new Set((
    'the and for with from that this you your are was were how what why when who can will not but all '
    + 'new now its has have had into out our via using use used just more than about over get got one two '
    + 'three any some they their them his her like make made does did been being also only most very here '
    + 'there which while where would could should after before first best better per off own day days '
    + 'week today year years time ways way thing things want need lot back still even really much many '
    + 'other every each onto show ask tell let say says said open source release released releases update '
    + 'updates updated version versions available introducing introduces announcing announced launch '
    + 'launches launched run running runs based model models llm llms ai new news post blog article '
    + 'guide learn learning build building built work working works help helps look looks looking free '
    + 'fast faster big good great part next last long better within without between across through '
    + 'toward towards against around under again why yet own may might must i\'m it\'s don\'t can\'t '
    + 'les des une pour avec dans sur par est sont qui que quoi aux ses son leur leurs plus pas cette '
    + 'ces cet comme mais donc elle ils nous vous tout tous toute toutes entre sans sous vers chez afin '
    + 'ainsi lors peut fait faire etre avoir nouveau nouvelle nouveaux nouvelles permet grace deux trois '
    + 'modele modeles outil outils mise jour jours semaine annonce annonces lance sortie ia '
    + 'using vs pr hn re de la le et en au du un ou a l d s t'
  ).split(/\s+/));

  // Les mots d'un titre, accents retirés, avec une marque : le mot portait-il une
  // majuscule ou un chiffre ailleurs qu'en tête de titre ? C'est la trace d'un nom
  // propre — Opus, Mica, GPT-6 — là où « trained » ou « decision » ne sont que de
  // l'anglais courant, qui monte et descend sans rien signifier.
  //
  // Un titre « En Capitales À Chaque Mot », à l'anglo-saxonne, ne dit rien de ses noms
  // propres : ses majuscules n'y sont pas comptées.
  const motsDe = titre => {
    const bruts = [...String(titre || '').normalize('NFD').replace(/[̀-ͯ]/g, '')
      .matchAll(/[A-Za-z0-9][A-Za-z0-9+#.\-]*[A-Za-z0-9+#]|[A-Za-z0-9]/g)].map(r => r[0].replace(/\.+$/, ''));
    const longs = bruts.filter(b => b.length > 3);
    const capitales = longs.length >= 3 && longs.filter(b => /^[A-Z]/.test(b)).length / longs.length >= 0.7;
    return bruts.map((brut, k) => {
      // Pluriel simple ramené au singulier, pour ne pas compter « agents » et
      // « agent » comme deux sujets. Les mots en -ss (« class ») sont épargnés.
      let m = brut.toLowerCase();
      if (m.length >= 5 && m.endsWith('s') && !m.endsWith('ss') && !/\d/.test(m)) m = m.slice(0, -1);
      return {m, propre: /\d/.test(brut) || (!capitales && k > 0 && /^[A-Z]/.test(brut))};
    });
  };
  const motUtile = m => m.length >= 3 && !MOTS_VIDES.has(m) && !MOTS_VIDES.has(m + 's')
    && !/^v?\d[\d.\-x]*$/.test(m) && !/^\d+(k|m|b|gb|mb|tb|ms|s|x|%)?$/.test(m);

  // Les termes d'un titre : ses mots utiles, et ses paires de mots utiles adjacents —
  // « claude code » dit autre chose que « claude » et « code » pris séparément.
  // Renvoie terme -> vrai si l'occurrence a l'allure d'un nom propre.
  function termesDe(titre){
    const mots = motsDe(titre);
    const sortie = new Map();
    mots.forEach(({m, propre}, k) => {
      if (!motUtile(m)) return;
      sortie.set(m, (sortie.get(m) || false) || propre);
      const suivant = mots[k + 1];
      if (suivant && motUtile(suivant.m)) sortie.set(m + ' ' + suivant.m, true);
    });
    return sortie;
  }

  function rendreTendances(){
    const chrono = [...D.jours].reverse();                 // du plus ancien au plus récent
    if (!chrono.length) {
      flux.innerHTML = `<p class="vide">${DESSIN_VIDE}Pas encore d'archive à analyser.</p>`;
      return resumer(0, VUES.tendances);
    }
    const dates = joursEntre(chrono[0].date, chrono[chrono.length - 1].date);
    const dernier = dates[dates.length - 1];
    const items = chrono.flatMap(j => j.items.filter(i => !estSignet(i)).map(i => ({i, date: j.date})));
    const essentiels = items.filter(x => x.i.voie === 'essentiel');
    const versions = items.filter(x => x.i.version);
    const absents = dates.filter(d => !PAR_DATE.has(d));

    // Les quatre dernières semaines servent de fenêtre aux courbes, et la dernière est
    // comparée aux trois précédentes. Les jours sans édition ne comptent pas : ils
    // feraient passer une panne pour une accalmie.
    const fenetre = dates.slice(-28);
    const recents = new Set(fenetre.slice(-7));
    const nRecents = fenetre.slice(-7).filter(d => PAR_DATE.has(d)).length || 1;
    const nAvant = fenetre.slice(0, -7).filter(d => PAR_DATE.has(d)).length || 1;
    const indexFenetre = new Map(fenetre.map((d, k) => [d, k]));

    const html = [];

    // -- les chiffres
    const claudeEss = essentiels.filter(x => x.i.prioritaire).length;
    const sourcesRecentes = new Set(items.filter(x => recents.has(x.date)).map(x => x.i.source_nom));
    html.push(`<div class="chiffres">`
      + chiffre(nf.format(items.length), 'éléments collectés')
      + chiffre(nf.format(essentiels.length), 'essentiels', true)
      + chiffre(essentiels.length ? Math.round(claudeEss / essentiels.length * 100) + ' %' : '—', 'de l\'essentiel sur Claude')
      + chiffre(nf.format(versions.length), 'versions publiées')
      + chiffre(nf.format(sourcesRecentes.size), 'sources actives en 7 jours')
      + chiffre(nf.format(absents.length), absents.length > 1 ? 'jours sans édition' : 'jour sans édition')
      + `</div>`);

    // -- le rythme
    const bilans = dates.map(d => ({d, b: bilan(PAR_DATE.get(d)), la: PAR_DATE.has(d)}));
    const max = Math.max(1, ...bilans.map(x => x.b.total));
    const moyenne = items.length / Math.max(1, dates.length - absents.length);
    const record = bilans.reduce((a, x) => x.b.total > a.b.total ? x : a, bilans[0]);
    html.push(section('Le rythme',
      `Une colonne par journée : l'essentiel en bas, puis l'utile, puis le bruit. `
      + `Un clic ouvre la journée.`,
      `<div class="rythme" role="group" aria-label="Éléments par journée">`
      + bilans.map(x => {
        const h = v => `height:${(v / max * 100).toFixed(2)}%`;
        if (!x.la) {
          return `<span class="r-jour absent" data-info="${echapper(libelleCourt(x.d))} — pas d'édition"></span>`;
        }
        const info = `${libelleCourt(x.d)} — ${x.b.total} éléments · ${x.b.ess} essentiel${x.b.ess > 1 ? 's' : ''} · ${x.b.utile} utile${x.b.utile > 1 ? 's' : ''}`;
        return `<button class="r-jour" data-date="${x.d}" data-info="${echapper(info)}" aria-label="${echapper(info)}"`
          + `${x.d === jourActif ? ' aria-current="date"' : ''}>`
          + `<i class="r-ess" style="${h(x.b.ess)}"></i><i class="r-utile" style="${h(x.b.utile)}"></i>`
          + `<i class="r-bruit" style="${h(x.b.bruit)}"></i></button>`;
      }).join('')
      + `</div><div class="r-axe">${axeMois(dates, false)}</div>`
      + `<p class="r-info" aria-live="polite">&nbsp;</p>`
      + `<p class="legende"><span><span class="pastille ess"></span>essentiel</span>`
      + `<span><span class="pastille utile"></span>utile</span><span><span class="pastille bruit"></span>bruit</span>`
      + `<span><b>${nf.format(Math.round(moyenne))}</b> éléments par jour en moyenne</span>`
      + `<span>record : <b>${record.b.total}</b> le ${echapper(libelleCourt(record.d))}</span></p>`
      + (absents.length
        ? `<p class="r-note">Jours sans édition — ${absents.map(d => echapper(libelleCourt(d))).join(', ')} : `
          + `l'édition suivante a repris ce que sa fenêtre de collecte couvrait encore.</p>`
        : '')));

    // -- les sujets qui montent
    const parTerme = new Map();     // terme -> tableau de comptes par jour de la fenêtre
    const propres = new Map();      // terme -> nombre d'occurrences en nom propre
    items.forEach(x => {
      if (x.i.voie === 'bruit' || !indexFenetre.has(x.date)) return;
      const k = indexFenetre.get(x.date);
      termesDe(x.i.titre).forEach((propre, t) => {
        let serie = parTerme.get(t);
        if (!serie) parTerme.set(t, serie = new Array(fenetre.length).fill(0));
        serie[k]++;
        if (propre) propres.set(t, (propres.get(t) || 0) + 1);
      });
    });
    const candidats = [...parTerme].map(([t, serie]) => {
      const r = serie.slice(-7).reduce((a, b) => a + b, 0);
      const a = serie.slice(0, -7).reduce((a, b) => a + b, 0);
      const tauxR = r / nRecents, tauxA = a / nAvant;
      const total = r + a;
      return {t, serie, r, a, ratio: (tauxR + 0.1) / (tauxA + 0.1),
        poids: r * Math.log2((tauxR + 0.1) / (tauxA + 0.1)),
        propre: (propres.get(t) || 0) / total >= 0.5};
    // Un mot courant ne passe que s'il monte franchement ; un nom propre ou une paire
    // de mots, dès trois titres. Un mot presque toujours pris dans la même paire —
    // « face » dans « hugging face » — laisse la paire concourir à sa place.
    }).filter(c => c.ratio >= 1.6 && (c.propre ? c.r >= 3 : c.r >= 6))
      .filter(c => c.t.includes(' ') || ![...parTerme].some(([b, serie]) =>
        b.includes(' ') && b.split(' ').includes(c.t)
        && serie.reduce((x, y) => x + y, 0) >= 0.8 * (c.r + c.a)));
    candidats.sort((x, y) => y.poids - x.poids);
    // Un mot seul s'efface derrière la paire qui le contient, quand il n'apparaît
    // guère ailleurs : « code » n'apprend rien à côté de « claude code ».
    const retenus = [];
    for (const c of candidats) {
      if (retenus.length >= 10) break;
      const couvert = retenus.some(x => (x.t.includes(' ') && x.t.split(' ').includes(c.t) && c.r <= x.r * 1.6)
        || (c.t.includes(' ') && c.t.split(' ').includes(x.t) && x.r <= c.r * 1.6));
      // La paire remplace le mot seul déjà retenu qu'elle contient : elle en dit plus.
      const englobe = retenus.findIndex(x => c.t.includes(' ') && c.t.split(' ').includes(x.t) && x.r <= c.r * 1.6);
      if (englobe >= 0) { retenus[englobe] = c; continue; }
      if (!couvert) retenus.push(c);
    }
    const constants = [...parTerme].map(([t, serie]) => ({t, total: serie.reduce((a, b) => a + b, 0)}))
      .filter(c => !c.t.includes(' ') && !retenus.some(x => x.t === c.t))
      .sort((x, y) => y.total - x.total).slice(0, 8);
    html.push(section('Les sujets qui montent',
      `Les mots des titres plus fréquents cette semaine que les trois précédentes, `
      + `rapportés au nombre de journées. Un clic cherche le terme dans toute l'archive.`,
      (retenus.length
        ? `<ol class="termes">` + retenus.map(c =>
          `<li><button class="terme" data-q="${echapper(c.t)}" title="Chercher « ${echapper(c.t)} »">`
          + `<span class="t-nom">${echapper(c.t)}</span>`
          + courbe(lissage(c.serie), {recents: 7})
          + `<span class="t-n" title="Titres de la dernière semaine">${c.r}</span>`
          + `<span class="t-var">${c.a ? '×' + (c.ratio).toFixed(1).replace('.', ',') : 'nouveau'}</span>`
          + `</button></li>`).join('') + `</ol>`
        : `<p class="t-intro">Rien ne se détache nettement cette semaine.</p>`)
      + (constants.length
        ? `<p class="r-note">Toujours présents sur quatre semaines : ` + constants.map(c =>
          `<button class="lien-jour terme-court" data-q="${echapper(c.t)}">${echapper(c.t)}</button>`).join(' ') + `</p>`
        : '')));

    // -- les versions
    const parProduit = new Map();
    versions.forEach(x => {
      const nom = x.i.source_nom.replace(/\s*\(releases\)\s*$/i, '');
      if (!parProduit.has(nom)) parProduit.set(nom, []);
      parProduit.get(nom).push(x);
    });
    const produits = [...parProduit].sort((a, b) => b[1].length - a[1].length).slice(0, 6);
    const indexDate = new Map(dates.map((d, k) => [d, k]));
    const place = d => ((indexDate.get(d) || 0) / Math.max(1, dates.length - 1) * 100).toFixed(2);
    if (produits.length) {
      html.push(section('La cadence des versions',
        `Une piste par produit suivi, un point par version publiée. Un clic mène à l'élément.`,
        `<div class="pistes">` + produits.map(([nom, liste]) => {
          const jours = new Set(liste.map(x => x.date)).size;
          const cadence = liste.length > 1
            ? `une tous les ${(dates.length / liste.length).toFixed(1).replace('.', ',')} j` : '';
          return `<div class="p-nom">${echapper(nom)}<small>${liste.length} version${liste.length > 1 ? 's' : ''}`
            + `${cadence ? ' · ' + cadence : ''}</small></div>`
            + `<div class="p-piste">` + liste.map((x, k) =>
              `<button class="p-point" data-date="${x.date}" data-ancre="${ancre(x.i.url)}"`
              // Plusieurs versions le même jour : les points s'écartent en hauteur
              // plutôt que de s'empiler en un seul.
              + ` style="left:${place(x.date)}%; --j:${jours < liste.length ? (k % 3) - 1 : 0}"`
              + ` title="${echapper(x.i.titre)} — ${echapper(libelleCourt(x.date))}"`
              + ` aria-label="${echapper(nom + ' ' + x.i.titre + ', ' + libelleCourt(x.date))}"></button>`).join('')
            + `</div>`;
        }).join('')
        + `<div class="p-axe">${axeMois(dates, true)}</div></div>`));
    }

    // -- les sources
    const parSource = new Map();
    items.forEach(x => {
      const nom = x.i.source_nom || '—';
      if (!parSource.has(nom)) parSource.set(nom, []);
      parSource.get(nom).push(x);
    });
    const joursDepuis = d => Math.round((new Date(dernier) - new Date(d)) / 86400000);
    const lignes = [...parSource].map(([nom, liste]) => {
      const notes = liste.filter(x => x.i.score != null);
      const utiles = liste.filter(x => x.i.voie !== 'bruit').length;
      const serie = new Array(fenetre.length).fill(0);
      liste.forEach(x => { if (indexFenetre.has(x.date)) serie[indexFenetre.get(x.date)]++; });
      const derniere = liste.reduce((m, x) => x.date > m ? x.date : m, '');
      return {
        nom, n: liste.length, utiles, pct: utiles / liste.length,
        ess: liste.filter(x => x.i.voie === 'essentiel').length,
        moy: notes.length ? notes.reduce((a, x) => a + x.i.score, 0) / notes.length : null,
        serie, derniere, silence: joursDepuis(derniere),
      };
    }).sort((a, b) => b.ess - a.ess || b.pct - a.pct || b.n - a.n);
    html.push(section('Ce que rapporte chaque source',
      `Sur toute l'archive affichée : combien d'éléments, quelle part passe le filtre de `
      + `l'utile, combien d'essentiels. Une source muette depuis plus de dix jours est signalée.`,
      `<div class="defile"><table class="t-sources"><thead><tr><th>Source</th><th>Éléments</th>`
      + `<th>Utiles</th><th>Essentiels</th><th class="col-large">Score moyen</th>`
      + `<th class="col-large">4 semaines</th><th class="col-large">Dernier</th></tr></thead><tbody>`
      + lignes.map(s => `<tr><td>${echapper(s.nom)}`
        + (s.silence > 10 ? `<span class="silence" title="Aucun élément depuis le ${echapper(libelleCourt(s.derniere))}">muette ${s.silence} j</span>` : '')
        + `</td><td>${s.n}</td>`
        + `<td>${Math.round(s.pct * 100)} %<span class="barre-pct" style="--p:${(s.pct * 100).toFixed(0)}%"></span></td>`
        + `<td>${s.ess || '·'}</td>`
        + `<td class="col-large">${s.moy == null ? '—' : s.moy.toFixed(2).replace('.', ',')}</td>`
        + `<td class="col-large">${courbe(lissage(s.serie), {l: 84, h: 20, recents: 7})}</td>`
        + `<td class="col-large">${echapper(dateCourte(s.derniere))}</td></tr>`).join('')
      + `</tbody></table></div>`));

    flux.innerHTML = `<div class="tendances">${html.join('')}</div>`;
    const periode = `du ${dateCourte(dates[0])} au ${dateCourte(dernier)}`;
    resumer(items.length, VUES.tendances, 'élément', periode);
  }

  const chiffre = (valeur, libelle, accent) =>
    `<div class="chiffre"><b${accent ? ' class="accent"' : ''}>${valeur}</b><span>${libelle}</span></div>`;
  const section = (titre, intro, corps) =>
    `<section class="t-section"><h2 class="t-titre">${titre}</h2>`
    + (intro ? `<p class="t-intro">${intro}</p>` : '') + corps + `</section>`;
  const dateCourte = d => {
    if (!d) return '—';
    const [a, m, j] = d.split('-').map(Number);
    return new Date(a, m - 1, j).toLocaleDateString('fr-FR', {day: 'numeric', month: 'short'});
  };

  // Survoler une colonne du rythme en donne le détail sous le graphique ; le clic, lui,
  // mène à la journée (voir le gestionnaire des renvois vers une journée).
  flux.addEventListener('mouseover', e => {
    const col = e.target instanceof Element && e.target.closest('.r-jour');
    const info = flux.querySelector('.r-info');
    if (col && info) info.textContent = col.dataset.info;
  });

  // Un terme cherche dans toute l'archive, depuis l'onglet Veille.
  flux.addEventListener('click', e => {
    const t = e.target instanceof Element && e.target.closest('[data-q]');
    if (t) {
      changerVue('veille', () => {
        champ.value = t.dataset.q;
        champ.dispatchEvent(new Event('input'));
        window.scrollTo(0, 0);
      });
      return;
    }
    const point = e.target instanceof Element && e.target.closest('.p-point');
    if (point) {
      changerVue('veille', () => {
        if (voie !== 'tout') voie = 'tout';
        allerA(point.dataset.date);
        history.replaceState(null, '', '#' + point.dataset.ancre);
        allerAncre();
      });
    }
  });

  // ---- écouter le point du jour ----
  // La synthèse du matin se lit aussi bien à voix haute, pendant qu'on fait autre
  // chose. La voix est celle du système, en français : rien ne sort de l'appareil,
  // et le bouton n'apparaît que si le navigateur sait parler.
  const VOIX = 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
  const boutonEcouter = `<button class="ecouter" aria-pressed="false" title="Lire le point du jour à voix haute">`
    + `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true">`
    + `<path d="M2.5 6v4h2.5l3.5 3V3L5 6z" fill="currentColor" stroke-linejoin="round"/>`
    + `<path class="onde" d="M10.8 5.6a3.4 3.4 0 0 1 0 4.8"/><path class="onde" d="M12.7 3.8a6 6 0 0 1 0 8.4"/>`
    + `</svg><span>Écouter</span></button>`;

  function ecouter(bouton){
    const parle = bouton.getAttribute('aria-pressed') === 'true';
    speechSynthesis.cancel();
    document.querySelectorAll('.ecouter[aria-pressed="true"]').forEach(b => {
      b.setAttribute('aria-pressed', 'false');
      b.querySelector('span').textContent = 'Écouter';
    });
    if (parle) return;
    const bloc = bouton.closest('.digest').querySelector('.retenir');
    // Une phrase par puce, lue avec une pause : lu d'un seul tenant, le texte perdait
    // la frontière entre deux idées. Le gras et le code n'ont pas de voix.
    const phrases = [...bloc.querySelectorAll('li')].map(li => li.textContent.trim()).filter(Boolean);
    const voix = speechSynthesis.getVoices().filter(v => v.lang && v.lang.toLowerCase().startsWith('fr'));
    const choix = voix.find(v => /natural|neural|premium|enhanced/i.test(v.name)) || voix[0] || null;
    (phrases.length ? phrases : [bloc.textContent]).forEach((texte, k, tout) => {
      const u = new SpeechSynthesisUtterance(texte);
      u.lang = 'fr-FR';
      if (choix) u.voice = choix;
      u.rate = 1.02;
      if (k === tout.length - 1) {
        u.onend = u.onerror = () => {
          bouton.setAttribute('aria-pressed', 'false');
          bouton.querySelector('span').textContent = 'Écouter';
        };
      }
      speechSynthesis.speak(u);
    });
    bouton.setAttribute('aria-pressed', 'true');
    bouton.querySelector('span').textContent = 'Arrêter';
  }

  flux.addEventListener('click', e => {
    const b = e.target instanceof Element && e.target.closest('.ecouter');
    if (b) ecouter(b);
  });
  // Une lecture en cours ne survit pas au départ de la page, ni au changement de jour.
  window.addEventListener('pagehide', () => { if (VOIX) speechSynthesis.cancel(); });

  function rendre(){
    // Les deux barres se rafraîchissent avant tout retour anticipé : chacune se masque
    // d'elle-même hors de sa vue, encore faut-il qu'on l'appelle.
    rendreRail();
    rendreNavJour();
    rendreNavSemaine();
    flux.parentElement.classList.toggle('pleine', vue === 'tendances');
    if (vue === 'semaine') return rendreSemaine();
    if (vue === 'favoris') return rendreFavoris();
    if (vue === 'tendances') return rendreTendances();
    const portee = joursAffiches();
    let visibles = 0;
    const html = portee.map(j => {
      const items = ordonner(j.items.filter(garde));
      if (!items.length) return '';
      visibles += items.length;
      // Le digest rédigé porte sur la veille : il n'a rien à faire dans les signets.
      const digests = (vue === 'veille' && filtre === 'tout' && !requete)
        // Le point du jour se lit d'emblée ; le détail, qui répète élément par élément
        // ce que la liste dit maintenant elle-même, se replie.
        ? j.digests.map(d =>
            `<div class="digest">`
            // Un seul élément de flex, sinon l'heure passe à la ligne sous le titre :
            // le filet pointillé qui suit prend toute la place restante.
            + `<p class="chapitre"><span><b>Le point</b>${d.heure ? ' de ' + echapper(d.heure) : ''}</span>`
            + (VOIX && d.retenir ? boutonEcouter : '') + `</p>`
            + (d.retenir ? `<div class="corps retenir">${d.retenir}</div>` : '')
            + (d.html
              ? `<details class="detail-jour"><summary>Le détail, section par section</summary>`
                + `<div class="corps">${d.html}</div></details>`
              : '')
            + `</div>`).join('')
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
      ? `<p class="vide">${DESSIN_VIDE}Aucun signet relevé pour l'instant.<br><br>`
        + `Lancer une fois <code>python run_signets.py --connexion</code> pour ouvrir la `
        + `session X, puis le relevé se fait tout seul à chaque synchronisation.</p>`
      : portee.length === 1 && !requete
        ? `<p class="vide">${DESSIN_VIDE}Rien ce jour-là dans cette voie.<br><br>`
          + `Élargir la voie ci-dessus, ou passer à la journée précédente avec &lsaquo;.</p>`
        : `<p class="vide">${DESSIN_VIDE}Aucun élément ne correspond.</p>`);
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
    urlsVisibles = [...flux.querySelectorAll('.enveloppe [data-url]')].map(b => b.dataset.url)
      .filter((u, k, t) => t.indexOf(u) === k);
    if (vue === 'veille') {
      document.getElementById('compteurs').insertAdjacentHTML('beforeend', '<span class="lecture" id="lecture"></span>');
      rendreLecture();
    }
  }

  // ---- progression de lecture ----
  // « 7 lus sur 20 » se lit d'un trait, sans compter les lignes estompées. La jauge
  // porte sur la journée entière, lus masqués compris : elle dit où l'on en est de la
  // journée, pas ce qui reste à l'écran.
  let urlsVisibles = [];
  let dernierLot = null;     // le dernier « tout marquer lu », qu'on peut annuler

  function rendreLecture(){
    const bloc = document.getElementById('lecture');
    if (!bloc) return;
    const portee = joursAffiches().flatMap(j => j.items)
      .filter(i => !estSignet(i) && VOIES[voie].ok(i) && sujetOk(i) && texteOk(i));
    const total = portee.length;
    const nLus = portee.filter(i => lus.has(i.url)).length;
    const restants = urlsVisibles.filter(u => !lus.has(u)).length;
    bloc.innerHTML = !total ? '' :
      `<span class="jauge" style="--p:${(nLus / total * 100).toFixed(1)}%" aria-hidden="true"><i></i></span>`
      + `<span><b>${nLus}</b>/${total} lu${nLus > 1 ? 's' : ''}</span>`
      + ((nLus || masquerLus)
        ? `<button class="bt-texte" id="masquer-lus" aria-pressed="${masquerLus}">`
          + `${masquerLus ? 'Afficher les lus' : 'Masquer les lus'}</button>` : '')
      + (dernierLot
        ? `<button class="bt-texte" id="annuler-lu">Annuler</button>`
        : restants ? `<button class="bt-texte" id="tout-lu" title="Marque comme lus les ${restants} éléments affichés">Tout marquer lu</button>` : '');
  }

  document.getElementById('compteurs').addEventListener('click', e => {
    const b = e.target instanceof Element && e.target.closest('button');
    if (!b) return;
    if (b.id === 'masquer-lus') {
      masquerLus = !masquerLus;
      try { localStorage.setItem('veille-masquer-lus', masquerLus ? '1' : '0'); } catch (err) {}
    } else if (b.id === 'tout-lu') {
      dernierLot = urlsVisibles.filter(u => !lus.has(u));
      dernierLot.forEach(u => lus.add(u));
      ecrireLus();
    } else if (b.id === 'annuler-lu' && dernierLot) {
      dernierLot.forEach(u => lus.delete(u));
      ecrireLus();
      dernierLot = null;
    } else return;
    const garderLot = dernierLot;
    rendreVoies(); rendreSujets(); rendre();
    dernierLot = garderLot;
    rendreLecture();
  });

  function rendreFavoris(){
    const section = sectionFavoris();
    flux.innerHTML = section.html || (listeFavoris().length
      ? `<p class="vide">${DESSIN_VIDE}Aucun favori ne correspond.</p>`
      : `<p class="vide">${DESSIN_VIDE}Aucun favori pour l'instant.<br><br>`
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
      panneau.innerHTML = `<p class="attente en-cours">Lecture de l'article…</p>`;
      try {
        const r = await fetch(D.worker + '/?url=' + encodeURIComponent(cible));
        const d = await r.json();
        contenu = d.texte || '';
      } catch (e) { contenu = ''; }
    }

    panneau.innerHTML = `<p class="attente en-cours">Rédaction par Gemini…</p>`;
    try {
      const corps = await appelerGemini(cle, promptDeveloppement(item, contenu),
        etat => { panneau.innerHTML = `<p class="attente en-cours">${etat}</p>`; });
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

  // Les Flash de Gemini saturent par vagues (« high demand », 503) : chaque modèle a
  // droit à trois essais espacés, puis on passe au suivant — la même chaîne que le
  // pipeline quotidien. Une clé refusée l'est partout : on s'arrête tout de suite.
  const TRANSITOIRES = new Set([429, 500, 502, 503, 504]);
  const pause = ms => new Promise(r => setTimeout(r, ms));

  async function appelerGemini(cle, prompt, signaler = () => {}){
    const modeles = D.modeles && D.modeles.length ? D.modeles : ['gemini-flash-latest'];
    let derniere = null;
    for (const [rang, modele] of modeles.entries()) {
      if (rang) signaler(`Gemini saturé — essai avec ${echapper(modele)}…`);
      for (let essai = 0; essai < 3; essai++) {
        if (essai) {
          signaler(`Gemini saturé — nouvel essai dans ${essai * 4} s…`);
          await pause(essai * 4000);
        }
        let reponse;
        try {
          reponse = await fetch(
            `https://generativelanguage.googleapis.com/v1beta/models/${modele}:generateContent`,
            {
              method: 'POST',
              headers: {'x-goog-api-key': cle, 'Content-Type': 'application/json'},
              body: JSON.stringify({
                contents: [{parts: [{text: prompt}]}],
                generationConfig: {maxOutputTokens: 12000, temperature: 0.3}
              })
            }
          );
        } catch (e) { derniere = e; break; }   // réseau : modèle suivant
        const donnees = await reponse.json().catch(() => ({}));
        if (reponse.ok) {
          const parts = ((donnees.candidates || [])[0] || {}).content;
          const texte = ((parts && parts.parts) || []).map(p => p.text || '').join('').trim();
          if (!texte) throw new Error('réponse vide du modèle');
          return texte;
        }
        const message = (donnees.error && donnees.error.message) || ('HTTP ' + reponse.status);
        if ([400, 401, 403].includes(reponse.status)) throw new Error('clé refusée — ' + message);
        derniere = new Error(message);
        if (!TRANSITOIRES.has(reponse.status)) break;   // 404 : modèle retiré, au suivant
      }
    }
    throw new Error(`Gemini est saturé sur tous les modèles essayés (${modeles.join(', ')}). `
      + `Réessaie dans quelques minutes. Dernière réponse : ${derniere ? derniere.message : '—'}`);
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
    panneau.innerHTML = `<p class="attente en-cours">Lecture de l'article et rédaction…</p>`;
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
      b.classList.remove('pop');
      if (marque) { void b.offsetWidth; b.classList.add('pop'); }   // relance l'animation
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
    rendreLecture();
    // Le curseur du clavier suit la souris : j reprend là où l'on vient de cliquer.
    const k = enveloppes().indexOf(carte.closest('.enveloppe'));
    if (k >= 0) curseur = k;
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
    // Le radar de la barre d'état balaie tant qu'il y a du neuf à lire.
    etat.classList.add('du-neuf');
    etat.querySelector('.nom').title = `${neufs.length} nouveauté${neufs.length > 1 ? 's' : ''} depuis votre dernière visite`;
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
