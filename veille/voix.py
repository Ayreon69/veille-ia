"""
Le point du jour lu par une voix de synthèse Gemini, plutôt que par celle du système.

La voix du navigateur dépend de l'appareil, et sur un téléphone elle est souvent
robotique. Gemini produit une voix naturelle, mais pas depuis la page : il faudrait la
clé de chaque lecteur. L'audio est donc fabriqué UNE fois par jour, dans le workflow,
avec la clé du dépôt, et publié à côté du site public (`voix/AAAA-MM-JJ.mp3`). Il
n'est jamais versionné : un fichier de 200 Ko par jour gonflerait l'historique, et le
site ne lit de toute façon que le point du jour.

La page essaie ce fichier, et retombe sur la voix du système s'il n'existe pas.

Usage :
    python -m veille.voix --vers site-public/voix
"""
import argparse
import base64
import io
import os
import re
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

import httpx

from . import config, site

_BASE = "https://generativelanguage.googleapis.com/v1beta"
MODELES = [
    m.strip()
    for m in os.getenv("VEILLE_VOIX_MODELES", "gemini-3.8-flash-tts,gemini-2.5-flash-preview-tts").split(",")
    if m.strip()
]
VOIX = os.getenv("VEILLE_VOIX", "Aoede")
_CONSIGNE = (
    "Lis ce texte en français, sur le ton posé et chaleureux d'une chronique radio du "
    "matin, avec une courte pause entre deux idées :\n\n"
)
_MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
         "septembre", "octobre", "novembre", "décembre"]


def _a_lire(puce: str) -> str:
    """Une puce telle qu'on la dit : sans liens (« github.com » lu à voix haute n'apprend
    rien), sans gras, et le tiret du titre devient une pause."""
    texte = re.sub(r"\[[^\]]*\]\([^)]*\)", "", puce.strip().lstrip("-*").strip())
    texte = texte.replace("**", "").replace("`", "")
    texte = re.sub(r"\s+—\s+", ". ", texte, count=1)
    return " ".join(texte.split()).rstrip(" .") + "."


def texte_du_point(jour: dict) -> str:
    """Le texte lu : « À retenir » du premier digest du jour, sans markdown."""
    for digest in jour.get("digests", []):
        retenir = site._section_a_retenir(digest.get("corps", ""))[0]
        puces = [
            _a_lire(ligne)
            for ligne in retenir.splitlines()
            if ligne.strip().startswith(("-", "*"))
        ]
        if puces:
            a, m, j = (int(x) for x in jour["date"].split("-"))
            entete = f"Le point du {j}{'er' if j == 1 else ''} {_MOIS[m - 1]}."
            return "\n\n".join([entete, *puces])
    return ""


def _en_wav(donnees: bytes, type_mime: str) -> bytes:
    """Gemini renvoie selon le modèle un WAV complet ou du PCM brut 24 kHz."""
    if donnees[:4] == b"RIFF" or "wav" in type_mime.lower():
        return donnees
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(donnees)
    return tampon.getvalue()


def synthetiser(texte: str) -> bytes:
    """Renvoie l'audio WAV du texte. Essaie chaque modèle, avec patience sur les 429/503 :
    le tier gratuit des voix n'accepte que quelques requêtes par minute."""
    cle = os.environ.get("GEMINI_API_KEY", "").strip()
    if not cle:
        raise RuntimeError("GEMINI_API_KEY absente")
    derniere = ""
    for modele in MODELES:
        for essai in range(4):
            reponse = httpx.post(
                f"{_BASE}/models/{modele}:generateContent",
                headers={"x-goog-api-key": cle},
                json={
                    "contents": [{"parts": [{"text": _CONSIGNE + texte}]}],
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {
                            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOIX}}
                        },
                    },
                },
                timeout=180,
            )
            if reponse.status_code == 200:
                partie = reponse.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
                return _en_wav(base64.b64decode(partie["data"]), partie.get("mimeType", ""))
            derniere = f"{modele} : {reponse.status_code}"
            if reponse.status_code not in (429, 500, 503) or essai == 3:
                break
            time.sleep(20 * (essai + 1))
    raise RuntimeError(f"aucune voix produite ({derniere})")


def en_mp3(wav: bytes) -> bytes | None:
    """Compresse en MP3 (~200 Ko la minute au lieu de 3 Mo) si ffmpeg est là."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    resultat = subprocess.run(
        [ffmpeg, "-loglevel", "error", "-i", "pipe:0", "-c:a", "libmp3lame", "-b:a", "64k",
         "-f", "mp3", "pipe:1"],
        input=wav, capture_output=True, check=False,
    )
    return resultat.stdout if resultat.returncode == 0 and resultat.stdout else None


def produire(dossier: Path) -> Path | None:
    """Écrit la voix du dernier point du jour dans `dossier`. None s'il n'y a rien à lire."""
    jours = site.charger_jours(1)
    if not jours:
        return None
    texte = texte_du_point(jours[0])
    if not texte:
        return None
    wav = synthetiser(texte)
    mp3 = en_mp3(wav)
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"{jours[0]['date']}.{'mp3' if mp3 else 'wav'}"
    chemin.write_bytes(mp3 or wav)
    return chemin


def main() -> int:
    parseur = argparse.ArgumentParser(description="Voix du point du jour.")
    parseur.add_argument("--vers", type=Path, default=config.RACINE / "site-public" / "voix")
    args = parseur.parse_args()
    chemin = produire(args.vers)
    if chemin:
        print(f"Voix du point du jour : {chemin} ({chemin.stat().st_size // 1024} Ko, voix {VOIX})")
    else:
        print("Aucun point du jour à lire.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
