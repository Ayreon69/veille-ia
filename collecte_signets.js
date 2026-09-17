/*
 * Collecte des signets X — à coller dans la console du navigateur.
 *
 * Mode d'emploi :
 *   1. ouvrir https://x.com/i/bookmarks dans Chrome, connecté normalement
 *   2. F12, onglet « Console »
 *   3. coller tout ce fichier, puis Entrée
 *   4. laisser faire : la page défile seule, un fichier JSON se télécharge à la fin
 *   5. le relevé le récupère tout seul à la synchronisation suivante
 *
 * Pourquoi la console et non un marque-page exécutable : la politique de sécurité de
 * contenu de X bloque les `javascript:`. La console, elle, n'est pas concernée.
 *
 * Rien n'est envoyé nulle part : le script lit la page déjà affichée et produit un
 * fichier local. Aucun identifiant, aucun cookie n'est touché.
 */
(async () => {
  const MAX = 250;          // plafond de sécurité
  const PAUSE = 900;        // laisse à X le temps de charger la suite
  const STAGNATIONS = 4;    // arrêt après N défilements sans rien de neuf

  const vus = new Map();

  const collecter = () => {
    for (const article of document.querySelectorAll('article[data-testid="tweet"]')) {
      const href = [...article.querySelectorAll('a[href*="/status/"]')]
        .map((a) => a.getAttribute('href'))
        .find((h) => /\/status\/\d+$/.test(h));
      if (!href) continue;

      const url = new URL(href, location.origin).href;
      if (vus.has(url)) continue;

      const texte = article.querySelector('[data-testid="tweetText"]');
      const heure = article.querySelector('time');

      // Tous les liens sortants de l'article, et non ceux de deux conteneurs précis :
      // X place la ressource tantôt dans le texte, tantôt dans une carte d'aperçu, dont
      // le sélecteur change. Viser large et filtrer sur le domaine est bien plus stable
      // — la version précédente ne trouvait de lien que dans 31 signets sur 169.
      const externe = (h) => {
        try {
          const u = new URL(h);
          return u.hostname === 't.co' || !/(^|\.)(x|twitter)\.com$/.test(u.hostname);
        } catch { return false; }
      };
      const liens = [...article.querySelectorAll('a[href]')]
        .map((a) => a.href)
        .filter(externe);

      vus.set(url, {
        url,
        auteur: (url.match(/\/([^/]+)\/status\//) || [, ''])[1],
        date: heure ? heure.getAttribute('datetime') : null,
        texte: texte ? texte.innerText.trim() : '',
        liens: [...new Set(liens)],
      });
    }
  };

  let stagnation = 0;
  while (vus.size < MAX && stagnation < STAGNATIONS) {
    const avant = vus.size;
    collecter();
    stagnation = vus.size === avant ? stagnation + 1 : 0;
    console.log(`  ${vus.size} signets…`);
    scrollBy(0, 2200);
    await new Promise((r) => setTimeout(r, PAUSE));
  }
  collecter();

  if (!vus.size) {
    console.warn(
      'Aucun signet trouvé. Vérifier qu\'on est bien sur https://x.com/i/bookmarks ' +
      'et que la liste est affichée.'
    );
    return;
  }

  const contenu = JSON.stringify(
    { genere: new Date().toISOString(), signets: [...vus.values()] }, null, 1
  );
  const lien = document.createElement('a');
  lien.href = URL.createObjectURL(new Blob([contenu], { type: 'application/json' }));
  lien.download = `signets-x-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.json`;
  lien.click();

  console.log(`%c${vus.size} signets exportés.`, 'color:#c2603a;font-weight:bold');
})();
