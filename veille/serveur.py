"""
Serveur local du site de veille.

Il existe pour une seule raison : **une page ouverte en `file://` ne peut rien faire
d'autre que s'afficher.** Elle ne peut pas appeler l'API — il faudrait lui confier la clé
Gemini en clair — ni écrire dans le vault. Servie depuis `http://127.0.0.1`, la même page
gagne les deux : la clé reste dans `.env`, côté serveur, et les favoris s'enregistrent
sans clic.

Ce que la page peut demander :

- `POST /api/developper` — développe un article (un appel modèle, mis en cache)
- `POST /api/favoris`    — enregistre les favoris dans le vault
- `GET  /api/etat`       — la page s'en sert pour savoir si elle est servie ou non

Tout le reste est du fichier statique pris dans `site/`.

Précautions, dans l'ordre où elles comptent :

- **Écoute sur 127.0.0.1 uniquement.** Rien n'est joignable depuis le réseau local.
- **Origine vérifiée.** Sans ce contrôle, n'importe quelle page ouverte dans le
  navigateur pourrait poster ici et déclencher des appels modèle à mon insu.
- **Extinction après inactivité.** Le processus n'a pas vocation à vivre indéfiniment ;
  sans fenêtre pour le rappeler, on l'oublierait.
"""
import json
import os
import socket
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import config, developpements, favoris, site, vault

HOTE = "127.0.0.1"
PORT = int(os.getenv("VEILLE_PORT_SITE", "8730"))
ADRESSE = f"http://{HOTE}:{PORT}/"

# Au-delà, le serveur s'éteint de lui-même. Assez long pour une session de lecture
# entrecoupée, assez court pour ne pas traîner jusqu'au lendemain.
INACTIVITE = 3 * 3600

FICHIER_LOG = config.DOSSIER_STATE / "serveur.log"

_ORIGINES = {f"http://{HOTE}:{PORT}", f"http://localhost:{PORT}"}

_derniere_requete = time.time()


def _journal(message: str) -> None:
    """Écrit dans state/serveur.log — le serveur tourne sans console."""
    FICHIER_LOG.parent.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now(config.FUSEAU).strftime("%d/%m %H:%M:%S")
    with open(FICHIER_LOG, "a", encoding="utf-8") as f:
        f.write(f"{horodatage}  {message}\n")


class Gestionnaire(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(site.DOSSIER_SITE), **kwargs)

    # ---- utilitaires ------------------------------------------------------

    def log_message(self, format, *args):  # noqa: A002 — signature imposée
        pass  # les requêtes de fichiers statiques n'apprennent rien

    def _repondre(self, charge: dict, code: int = 200) -> None:
        corps = json.dumps(charge, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def _origine_valide(self) -> bool:
        origine = self.headers.get("Origin")
        return origine is None or origine in _ORIGINES

    def _lire_json(self) -> dict:
        taille = int(self.headers.get("Content-Length") or 0)
        if taille <= 0:
            return {}
        return json.loads(self.rfile.read(taille).decode("utf-8"))

    # ---- routes -----------------------------------------------------------

    def do_GET(self):  # noqa: N802 — signature imposée
        global _derniere_requete
        _derniere_requete = time.time()

        if self.path.startswith("/api/etat"):
            return self._repondre({"ok": True, "modele": config.MODELE_GEMINI})
        return super().do_GET()

    def end_headers(self):
        # Le site est réécrit à chaque développement et à chaque synchronisation : mis
        # en cache par le navigateur, il afficherait la veille de la veille. L'en-tête
        # passe par ici et non par do_GET, où il précéderait la ligne de statut.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self):  # noqa: N802 — signature imposée
        global _derniere_requete
        _derniere_requete = time.time()

        if not self._origine_valide():
            _journal(f"POST refusé — origine {self.headers.get('Origin')!r}")
            return self._repondre({"erreur": "origine refusée"}, 403)

        routes = {"/api/developper": self._developper, "/api/favoris": self._favoris}
        route = routes.get(self.path.split("?")[0])
        if not route:
            return self._repondre({"erreur": "route inconnue"}, 404)

        try:
            return route(self._lire_json())
        except Exception as e:  # noqa: BLE001 — un échec ne doit pas tuer le serveur
            _journal(f"ERREUR {self.path} — {type(e).__name__}: {e}")
            return self._repondre({"erreur": f"{type(e).__name__}: {e}"}, 500)

    def _developper(self, charge: dict) -> None:
        item = charge.get("item") or {}
        if not item.get("url"):
            return self._repondre({"erreur": "item sans URL"}, 400)

        debut = time.time()
        entree = developpements.obtenir(item, refaire=bool(charge.get("refaire")))
        duree = time.time() - debut

        # Rien à reconstruire si le développement sortait du cache.
        if duree > 1:
            _journal(f"développé en {duree:.0f}s — {item['url']}")
            site.construire()

        return self._repondre({
            "url": entree["url"],
            "genere": entree["genere"],
            "html": site.markdown_html(entree["corps"]),
        })

    def _favoris(self, charge: dict) -> None:
        etat = favoris.charger()
        ajoutes, retires = favoris.fusionner(etat, charge)
        favoris.enregistrer(etat)
        vault.ecrire_favoris(favoris.note_markdown(etat))
        if ajoutes or retires:
            _journal(f"favoris : {len(etat['favoris'])} au total "
                     f"({ajoutes} ajouté(s), {retires} retiré(s))")
        return self._repondre({"total": len(etat["favoris"])})


def _surveiller(serveur: ThreadingHTTPServer) -> None:
    """Éteint le serveur après une longue inactivité."""
    while True:
        time.sleep(60)
        if time.time() - _derniere_requete > INACTIVITE:
            _journal(f"extinction après {INACTIVITE // 3600} h sans requête")
            threading.Thread(target=serveur.shutdown, daemon=True).start()
            return


def _port_occupe() -> bool:
    with socket.socket() as s:
        return s.connect_ex((HOTE, PORT)) == 0


def demarrer(ouvrir: bool = False) -> int:
    """Lance le serveur. S'il tourne déjà, ouvre simplement le navigateur."""
    if _port_occupe():
        # Cas normal quand on relance le raccourci : un serveur écoute déjà.
        if ouvrir:
            webbrowser.open(ADRESSE)
        return 0

    try:
        serveur = ThreadingHTTPServer((HOTE, PORT), Gestionnaire)
    except OSError as e:
        _journal(f"démarrage impossible — {e}")
        return 1

    _journal(f"démarré sur {ADRESSE}")
    threading.Thread(target=_surveiller, args=(serveur,), daemon=True).start()

    if ouvrir:
        webbrowser.open(ADRESSE)

    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        serveur.server_close()
        _journal("arrêté")
    return 0


if __name__ == "__main__":
    sys.exit(demarrer(ouvrir="--ouvrir" in sys.argv))
