"""Fabrique l'image de partage, une fois pour toutes.

Versionnée dans assets/ plutôt que produite à chaque construction : le contenu
change tous les jours, l'identité du site non, et un build ne doit pas dépendre de
Pillow. Les polices sont celles de la page.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

A = Path(__file__).parent
PAPIER, ENCRE, DOUX, OCRE = "#f8f6f1", "#16151a", "#6b6459", "#9a6410"

im = Image.new("RGB", (1200, 630), PAPIER)
d = ImageDraw.Draw(im)

# Le sous-ensemble de Fraunces a pour instance par défaut une graisse de 900 et une
# taille optique de 9 : Pillow rendait un titre bien plus gras que celui de la page,
# qui demande 400 en taille optique automatique. On règle les axes explicitement.
titre = ImageFont.truetype(str(A / "fraunces-latin.woff2"), 92)
titre.set_variation_by_axes([144, 400])
mono = ImageFont.truetype(str(A / "ibm-plex-mono-500-latin.woff2"), 26)
mono_p = ImageFont.truetype(str(A / "ibm-plex-mono-400-latin.woff2"), 24)
sans = ImageFont.truetype(str(A / "ibm-plex-sans-latin.woff2"), 32)

M = 88
d.ellipse((M, 86, M + 16, 102), fill=OCRE)
d.text((M + 32, 78), "V E I L L E   I A", font=mono, fill=ENCRE)

lignes = ["L'actualité de l'IA,", "en français, chaque jour."]
for k, ligne in enumerate(lignes):
    largeur = d.textlength(ligne, font=titre)
    assert largeur < 1200 - 2 * M, f"« {ligne} » déborde de {round(largeur)} px"
    d.text((M, 196 + k * 118), ligne, font=titre, fill=ENCRE)

d.text((M, 452), "Claude, les agents, les modèles et l'agentic coding —", font=sans, fill=DOUX)
d.text((M, 494), "collectés, notés et résumés automatiquement, tous les matins.", font=sans, fill=DOUX)

d.line((M, 566, 1200 - M, 566), fill="#ddd8cc", width=1)
d.text((M, 584), "VEILLE-IA-RJ.PAGES.DEV", font=mono_p, fill=DOUX)

im.save(A / "partage.png", "PNG", optimize=True)
print("écrit :", (A / "partage.png").stat().st_size // 1024, "Ko")
