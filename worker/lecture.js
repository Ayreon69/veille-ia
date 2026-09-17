/**
 * Worker de lecture d'articles pour le site public.
 *
 * Il existe pour une raison unique : un navigateur ne peut pas lire une page d'un autre
 * site. Sans lui, le bouton « développer » n'aurait que le titre et l'extrait à donner
 * au modèle — exactement le défaut qui avait produit une erreur factuelle en août, et
 * pour lequel la lecture du contenu a été mise en place côté serveur.
 *
 * Ce qu'il ne fait PAS, et c'est le plus important :
 *
 * - **il ne voit aucune clé.** Le lecteur ne lui envoie qu'une URL ; l'appel à Gemini
 *   part du navigateur, avec la clé du lecteur, directement vers Google.
 * - **il n'accepte pas n'importe quelle URL.** Sans liste blanche, ce serait un proxy
 *   ouvert offert à Internet, utilisable pour aller chercher n'importe quoi depuis
 *   l'infrastructure de quelqu'un d'autre. Seules les adresses effectivement publiées
 *   sur le site sont servies.
 *
 * Variable d'environnement attendue :
 *   SITE — origine du site public, ex. https://veille-ia.pages.dev
 *          Elle sert à la fois de source pour la liste blanche (SITE/urls.json) et
 *          d'origine autorisée en CORS.
 */

// Aligné sur LONGUEUR_LECTURE côté Python : en dessous, le modèle résume une
// introduction en croyant résumer l'article.
const LONGUEUR_MAX = 6000;

// Durée de mise en cache de la liste blanche. Le site est reconstruit une fois par jour ;
// une demi-heure suffit à absorber les rafales sans servir une liste périmée longtemps.
const CACHE_LISTE = 1800;

// Là où vit la prose. Cibler ces éléments plutôt que tout le document évite d'un seul
// coup les menus, les pieds de page et les scripts.
const PROSE = "article p, article li, main p, main li, p, h1, h2, h3, h4, li, pre, blockquote, td";

const entetes = (origine) => ({
  "Access-Control-Allow-Origin": origine,
  "Access-Control-Allow-Methods": "GET,OPTIONS",
  "Access-Control-Max-Age": "86400",
});

const json = (charge, origine, code = 200) =>
  new Response(JSON.stringify(charge), {
    status: code,
    headers: { "Content-Type": "application/json; charset=utf-8", ...entetes(origine) },
  });

/** Liste des URLs publiées, telle que le site la génère à chaque construction. */
async function autorisees(site) {
  const cache = caches.default;
  const cle = new Request(`${site}/urls.json`);

  let reponse = await cache.match(cle);
  if (!reponse) {
    reponse = await fetch(cle, { cf: { cacheTtl: CACHE_LISTE, cacheEverything: true } });
    if (!reponse.ok) throw new Error("liste des articles indisponible");
    reponse = new Response(reponse.body, reponse);
    reponse.headers.set("Cache-Control", `max-age=${CACHE_LISTE}`);
    await cache.put(cle, reponse.clone());
  }
  return new Set(await reponse.json());
}

/** Texte visible d'une page, dans l'ordre du document. */
async function lireTexte(url) {
  const reponse = await fetch(url, {
    headers: {
      "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      Accept: "text/html,application/xhtml+xml",
    },
    redirect: "follow",
    signal: AbortSignal.timeout(15000),
  });

  if (!reponse.ok) throw new Error(`la page a répondu ${reponse.status}`);
  const type = reponse.headers.get("content-type") || "";
  if (!type.includes("html") && !type.includes("text")) {
    throw new Error(`contenu non textuel (${type || "type inconnu"})`);
  }

  const morceaux = [];
  let taille = 0;

  const collecteur = {
    text(bout) {
      // On collecte au-delà de la limite : le texte arrive par fragments, et couper
      // trop tôt tronquerait au milieu d'un mot sans rien économiser d'utile.
      if (taille > LONGUEUR_MAX * 3) return;
      const t = bout.text.trim();
      if (!t) return;
      morceaux.push(t);
      taille += t.length;
    },
  };

  const transforme = new HTMLRewriter()
    .on("title", collecteur)
    .on(PROSE, collecteur)
    .transform(reponse);

  await transforme.text(); // consomme le flux, remplit `morceaux`

  let texte = morceaux.join("\n").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
  if (texte.length > LONGUEUR_MAX) {
    texte = texte.slice(0, LONGUEUR_MAX).replace(/\s+\S*$/, "") + "…";
  }
  return texte;
}

export default {
  async fetch(requete, env) {
    const site = (env.SITE || "").replace(/\/+$/, "");
    const origine = site || "*";

    if (requete.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: entetes(origine) });
    }
    if (requete.method !== "GET") {
      return json({ erreur: "méthode non autorisée" }, origine, 405);
    }
    if (!site) {
      return json({ erreur: "SITE non configuré sur le Worker" }, origine, 500);
    }

    const cible = new URL(requete.url).searchParams.get("url");
    if (!cible) return json({ erreur: "paramètre url manquant" }, origine, 400);

    let analysee;
    try {
      analysee = new URL(cible);
    } catch {
      return json({ erreur: "url invalide" }, origine, 400);
    }
    if (analysee.protocol !== "http:" && analysee.protocol !== "https:") {
      return json({ erreur: "protocole refusé" }, origine, 400);
    }

    // Le contrôle qui compte. Une URL absente du site n'est pas servie, quelle qu'elle
    // soit : c'est ce qui distingue ce Worker d'un proxy ouvert.
    try {
      const liste = await autorisees(site);
      if (!liste.has(cible)) {
        return json({ erreur: "url absente du site" }, origine, 403);
      }
    } catch (e) {
      return json({ erreur: String(e.message || e) }, origine, 503);
    }

    // Un article illisible n'est pas une erreur du service : la page sait développer
    // sans, et les consignes demandent au modèle de le signaler plutôt que de broder.
    try {
      return json({ texte: await lireTexte(cible) }, origine);
    } catch (e) {
      return json({ texte: "", erreur: String(e.message || e) }, origine);
    }
  },
};
