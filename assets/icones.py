"""Fabrique les icônes d'écran d'accueil du site publié, une fois pour toutes.

Même principe que partage.py : versionnées dans assets/, pour qu'une construction ne
dépende pas de Pillow. Le dessin est celui de la marque de la barre d'état — un radar,
deux cercles, un balai et un point — tracé quatre fois trop grand puis réduit, ce qui
tient lieu d'anticrénelage.

- icone-180.png : l'icône d'écran d'accueil d'iOS, qui ignore le manifeste ;
- icone-192.png, icone-512.png : celles du manifeste ;
- icone-masquable-512.png : la même, resserrée dans la zone sûre de 80 %, pour les
  lanceurs Android qui découpent l'icône en cercle ou en goutte.
"""
from pathlib import Path

from PIL import Image, ImageDraw

A = Path(__file__).parent
PAPIER, OCRE = (248, 246, 241), (154, 100, 16)
SUR = 4   # facteur de suréchantillonnage


def dessiner(cote: int, echelle: float, arrondi: bool) -> Image.Image:
    """Le radar au centre d'un carré de papier. `echelle` : rayon extérieur / côté."""
    s = cote * SUR
    fond = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(fond).rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22) if arrondi else 0,
                                           fill=PAPIER + (255,))

    calque = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(calque)
    c, r = s / 2, s * echelle
    trait = max(2, round(s * 0.028))
    boite = lambda rayon: (c - rayon, c - rayon, c + rayon, c + rayon)  # noqa: E731

    d.pieslice(boite(r), start=-90, end=0, fill=OCRE + (76,))                       # le balai
    d.ellipse(boite(r), outline=OCRE + (120,), width=trait)                          # cercle extérieur
    d.ellipse(boite(r * 0.59), outline=OCRE + (60,), width=max(2, trait * 3 // 4))   # cercle intérieur
    d.ellipse(boite(r * 0.29), fill=OCRE + (255,))                                   # le point

    return Image.alpha_composite(fond, calque).resize((cote, cote), Image.LANCZOS)


for nom, cote, echelle, arrondi in (
    ("icone-180.png", 180, 0.36, False),        # iOS arrondit lui-même
    ("icone-192.png", 192, 0.36, True),
    ("icone-512.png", 512, 0.36, True),
    ("icone-masquable-512.png", 512, 0.29, False),
):
    image = dessiner(cote, echelle, arrondi)
    # Le carré plein n'a pas besoin de transparence : l'aplatir allège le fichier.
    if not arrondi:
        image = image.convert("RGB")
    image.save(A / nom, "PNG", optimize=True)
    print(f"écrit : {nom} ({(A / nom).stat().st_size // 1024} Ko)")
