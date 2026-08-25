#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILET — le compagnon de téléchargement de L'Atelier.

Le navigateur ne peut pas récupérer des fichiers hébergés sur un autre site
(règle de sécurité CORS). C'est pour ça que cette partie de la boîte à outils
est un script à lancer sur sa machine.

Trois usages :

    python filet.py coran                  le Coran complet par un récitateur
    python filet.py page <url>             tous les audios trouvés sur une page
    python filet.py video <url>            YouTube et compagnie (via yt-dlp)

Aucune dépendance obligatoire : tout marche avec Python 3.8+ tel quel.
`yt-dlp` n'est nécessaire que pour la sous-commande `video`.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import queue
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser

NAVIGATEUR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# ═══════════════════════════════════════════════════════════════════════
#  Affichage
# ═══════════════════════════════════════════════════════════════════════

def _preparer_console() -> bool:
    """Fait parler la console en UTF-8 quand elle en est capable.

    Sans ça, la console Windows en cp1252 lève une exception dès le premier
    accent — et le script mourrait avant d'avoir rien téléchargé.
    """
    for flux in (sys.stdout, sys.stderr):
        try:
            # line_buffering : sans ça, rediriger la sortie vers un fichier
            # ou un tuyau ne montre plus rien avant la toute fin.
            flux.reconfigure(encoding="utf-8", errors="replace",
                             line_buffering=True)
        except Exception:
            try:
                flux.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    return "utf" in (getattr(sys.stdout, "encoding", "") or "").lower()


UNICODE_OK = _preparer_console()
COULEUR = bool(os.environ.get("FORCE_COLOR")) or (
    sys.stdout.isatty() and (os.name != "nt" or os.environ.get("WT_SESSION"))
)

FILET = "─" if UNICODE_OK else "-"
PUCE = "·" if UNICODE_OK else "-"


def _c(code: str, texte: str) -> str:
    return f"\033[{code}m{texte}\033[0m" if COULEUR else texte


jaune = lambda t: _c("33", t)
vert = lambda t: _c("32", t)
rouge = lambda t: _c("31", t)
gris = lambda t: _c("90", t)


def titre(texte: str) -> None:
    print()
    print(jaune("  " + texte))
    print(gris("  " + FILET * max(10, len(texte))))


def poids(octets: int) -> str:
    if octets < 1024:
        return f"{octets} o"
    for unite in ("Ko", "Mo", "Go"):
        octets /= 1024.0
        if octets < 1024:
            return f"{octets:.1f} {unite}"
    return f"{octets:.1f} To"


# ═══════════════════════════════════════════════════════════════════════
#  Téléchargement
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class Tache:
    url: str
    destination: str
    etiquette: str = ""
    taille: int = 0            # poids annoncé par le serveur, si connu


@dataclass
class Bilan:
    reussis: int = 0
    sautes: int = 0
    echecs: list = field(default_factory=list)
    octets: int = 0
    en_cours: dict = field(default_factory=dict)   # étiquette → octets reçus
    verrou: threading.Lock = field(default_factory=threading.Lock)


def ouvrir(url: str, debut: int = 0, referer: str = "") -> urllib.request.addinfourl:
    entetes = {"User-Agent": NAVIGATEUR, "Accept": "*/*"}
    if debut:
        entetes["Range"] = f"bytes={debut}-"
    if referer:
        entetes["Referer"] = referer
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=entetes), timeout=30
    )


def telecharger_un(tache: Tache, bilan: Bilan, essais: int = 4, referer: str = "") -> None:
    """Télécharge un fichier, reprenable, avec plusieurs tentatives.

    Le fichier est écrit en `.part` et renommé seulement une fois complet :
    une interruption ne laisse jamais un fichier tronqué à la bonne place.
    """
    final = tache.destination
    partiel = final + ".part"

    if os.path.exists(final) and os.path.getsize(final) > 0:
        with bilan.verrou:
            bilan.sautes += 1
            # Compté dans le total : sinon la barre en octets reculerait
            # à chaque reprise d'un téléchargement déjà bien avancé.
            bilan.octets += os.path.getsize(final)
        return

    os.makedirs(os.path.dirname(final) or ".", exist_ok=True)
    etiquette = tache.etiquette or os.path.basename(final)

    for essai in range(1, essais + 1):
        deja = os.path.getsize(partiel) if os.path.exists(partiel) else 0
        try:
            reponse = ouvrir(tache.url, deja, referer)

            # Le serveur ignore la reprise : on repart de zéro.
            if deja and reponse.status != 206:
                deja = 0

            mode = "ab" if deja else "wb"
            with bilan.verrou:
                bilan.en_cours[etiquette] = deja
            try:
                with open(partiel, mode) as sortie:
                    while True:
                        bloc = reponse.read(262144)
                        if not bloc:
                            break
                        sortie.write(bloc)
                        with bilan.verrou:
                            bilan.octets += len(bloc)
                            bilan.en_cours[etiquette] += len(bloc)
            finally:
                with bilan.verrou:
                    bilan.en_cours.pop(etiquette, None)

            reponse.close()

            if os.path.getsize(partiel) == 0:
                raise IOError("fichier vide")

            os.replace(partiel, final)
            with bilan.verrou:
                bilan.reussis += 1
            return

        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):          # inutile d'insister
                with bilan.verrou:
                    bilan.echecs.append((tache.etiquette or tache.url, f"HTTP {e.code}"))
                return
            raison = f"HTTP {e.code}"
        except Exception as e:                      # réseau, coupure, disque
            raison = type(e).__name__ + (f": {e}" if str(e) else "")

        if essai < essais:
            time.sleep(min(2 ** essai, 8))
        else:
            with bilan.verrou:
                bilan.echecs.append((tache.etiquette or tache.url, raison))


def lancer_lot(taches: list, fils: int, referer: str = "",
               octets_prevus: int = 0) -> Bilan:
    """Exécute les téléchargements sur plusieurs fils, avec une barre d'avancement.

    Quand le poids total est connu d'avance, la barre suit les octets plutôt
    que le nombre de fichiers : sur trois fichiers d'un gigaoctet, compter les
    fichiers donnerait une barre immobile pendant vingt minutes.
    """
    bilan = Bilan()
    total = len(taches)
    if not total:
        print(gris("  Rien à télécharger."))
        return bilan

    file = queue.Queue()
    for t in taches:
        file.put(t)

    depart = time.time()
    arret = threading.Event()

    def ouvrier():
        while not arret.is_set():
            try:
                tache = file.get_nowait()
            except queue.Empty:
                return
            try:
                telecharger_un(tache, bilan, referer=referer)
            finally:
                file.task_done()

    equipe = [threading.Thread(target=ouvrier, daemon=True) for _ in range(max(1, fils))]
    for f in equipe:
        f.start()

    try:
        while any(f.is_alive() for f in equipe):
            peindre_barre(bilan, total, octets_prevus, time.time() - depart)
            time.sleep(0.25)
    except KeyboardInterrupt:
        arret.set()
        print("\n" + jaune("  Interrompu. Relancez la même commande : "
                           "tout ce qui est déjà là sera sauté."))
        raise SystemExit(130)

    peindre_barre(bilan, total, octets_prevus, time.time() - depart)
    print()
    return bilan


def peindre_barre(bilan: Bilan, total: int, prevus: int, ecoule: float) -> None:
    with bilan.verrou:
        faits = bilan.reussis + bilan.sautes + len(bilan.echecs)
        octets = bilan.octets
        en_cours = list(bilan.en_cours.keys())

    if prevus > 0:
        part = min(1.0, octets / prevus)
        compteur = f"{poids(octets)} / {poids(prevus)}"
    else:
        part = faits / total if total else 1.0
        compteur = f"{faits}/{total}  {poids(octets)}"

    debit = octets / ecoule if ecoule > 1 else 0
    reste = ""
    if debit > 0:
        if prevus > 0:
            secondes = (prevus - octets) / debit
        elif faits:
            secondes = (total - faits) * (ecoule / faits)
        else:
            secondes = 0
        if secondes > 60:
            reste = f" · ~{int(secondes // 60)} min"
        elif secondes > 3:
            reste = f" · ~{int(secondes)} s"

    largeur = 28
    plein = int(part * largeur)
    ligne = ("  [" + "#" * plein + "." * (largeur - plein) + "] "
             + f"{compteur}  {poids(int(debit))}/s{reste}")
    if prevus > 0:
        ligne += f"  ({faits}/{total})"
    if en_cours:
        reste_place = max(0, 108 - len(ligne))
        if reste_place > 14:
            en_clair = en_cours[0][:reste_place - 5]
            ligne += gris("  " + en_clair)
            if len(en_cours) > 1:
                ligne += gris(f" +{len(en_cours) - 1}")

    barre.derniere = max(getattr(barre, "derniere", 0), len(ligne))
    sys.stdout.write("\r" + ligne.ljust(barre.derniere))
    sys.stdout.flush()


def barre(faits: int, total: int, octets: int, ecoule: float) -> None:
    """Barre simple, pour les étapes qui comptent des unités et non des octets."""
    part = faits / total if total else 1
    largeur = 28
    plein = int(part * largeur)
    sys.stdout.write("\r  [" + "#" * plein + "." * (largeur - plein)
                     + f"] {faits}/{total}    ")
    sys.stdout.flush()


def resumer(bilan: Bilan, dossier: str) -> None:
    print()
    print(f"  {vert('Terminé')} — {bilan.reussis} téléchargés, "
          f"{bilan.sautes} déjà présents, {len(bilan.echecs)} en échec.")
    print(gris(f"  Dossier : {os.path.abspath(dossier)}"))
    if bilan.echecs:
        print()
        print(rouge("  Échecs :"))
        for nom, raison in bilan.echecs[:20]:
            print(f"    · {nom} — {raison}")
        if len(bilan.echecs) > 20:
            print(f"    … et {len(bilan.echecs) - 20} autres.")
        print(gris("  Relancez la même commande pour ne réessayer que ceux-là."))


# ═══════════════════════════════════════════════════════════════════════
#  Noms de fichiers
# ═══════════════════════════════════════════════════════════════════════

INTERDITS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def nom_propre(nom: str, reserve: str = "fichier") -> str:
    nom = INTERDITS.sub(" ", urllib.parse.unquote(nom))
    nom = re.sub(r"\s+", " ", nom).strip(" .")
    return nom[:150] or reserve


# ═══════════════════════════════════════════════════════════════════════
#  MODE CORAN
# ═══════════════════════════════════════════════════════════════════════

SOURATES = [
    "Al-Fatiha", "Al-Baqara", "Al-Imran", "An-Nisa", "Al-Maida", "Al-Anam",
    "Al-Araf", "Al-Anfal", "At-Tawba", "Yunus", "Hud", "Yusuf", "Ar-Rad",
    "Ibrahim", "Al-Hijr", "An-Nahl", "Al-Isra", "Al-Kahf", "Maryam", "Ta-Ha",
    "Al-Anbiya", "Al-Hajj", "Al-Muminun", "An-Nur", "Al-Furqan", "Ash-Shuara",
    "An-Naml", "Al-Qasas", "Al-Ankabut", "Ar-Rum", "Luqman", "As-Sajda",
    "Al-Ahzab", "Saba", "Fatir", "Ya-Sin", "As-Saffat", "Sad", "Az-Zumar",
    "Ghafir", "Fussilat", "Ash-Shura", "Az-Zukhruf", "Ad-Dukhan", "Al-Jathiya",
    "Al-Ahqaf", "Muhammad", "Al-Fath", "Al-Hujurat", "Qaf", "Adh-Dhariyat",
    "At-Tur", "An-Najm", "Al-Qamar", "Ar-Rahman", "Al-Waqia", "Al-Hadid",
    "Al-Mujadila", "Al-Hashr", "Al-Mumtahina", "As-Saff", "Al-Jumua",
    "Al-Munafiqun", "At-Taghabun", "At-Talaq", "At-Tahrim", "Al-Mulk",
    "Al-Qalam", "Al-Haqqa", "Al-Maarij", "Nuh", "Al-Jinn", "Al-Muzzammil",
    "Al-Muddaththir", "Al-Qiyama", "Al-Insan", "Al-Mursalat", "An-Naba",
    "An-Naziat", "Abasa", "At-Takwir", "Al-Infitar", "Al-Mutaffifin",
    "Al-Inshiqaq", "Al-Buruj", "At-Tariq", "Al-Ala", "Al-Ghashiya", "Al-Fajr",
    "Al-Balad", "Ash-Shams", "Al-Layl", "Ad-Duha", "Ash-Sharh", "At-Tin",
    "Al-Alaq", "Al-Qadr", "Al-Bayyina", "Az-Zalzala", "Al-Adiyat", "Al-Qaria",
    "At-Takathur", "Al-Asr", "Al-Humaza", "Al-Fil", "Quraysh", "Al-Maun",
    "Al-Kawthar", "Al-Kafirun", "An-Nasr", "Al-Masad", "Al-Ikhlas", "Al-Falaq",
    "An-Nas",
]

# Nombre de versets par sourate (comptage Hafs).
VERSETS = [
    7, 286, 200, 176, 120, 165, 206, 75, 129, 109, 123, 111, 43, 52, 99, 128,
    111, 110, 98, 135, 112, 78, 118, 64, 77, 227, 93, 88, 69, 60, 34, 30, 73,
    54, 45, 83, 182, 88, 75, 85, 54, 53, 89, 59, 37, 35, 38, 29, 18, 45, 60,
    49, 62, 55, 78, 96, 29, 22, 24, 13, 14, 11, 11, 18, 12, 12, 30, 52, 52,
    44, 28, 28, 20, 56, 40, 31, 50, 40, 46, 42, 29, 19, 36, 25, 22, 17, 19,
    26, 30, 20, 15, 21, 11, 8, 8, 19, 5, 8, 8, 11, 11, 8, 3, 9, 5, 4, 7, 3,
    6, 3, 5, 4, 5, 6,
]

# Garde-fou : si l'une des deux tables est abîmée, on s'arrête tout de suite
# plutôt que de télécharger 6 000 fichiers de travers.
assert len(SOURATES) == 114, "la liste des sourates est incomplète"
assert len(VERSETS) == 114, "la liste des versets est incomplète"
assert sum(VERSETS) == 6236, f"total de versets incohérent : {sum(VERSETS)}"


# Chaque récitation connue, avec sa façon de fabriquer une URL.
#   base_sourate : {n:03d} → numéro de sourate
#   base_verset  : {s:03d}{v:03d} → sourate + verset collés
RECITATIONS = {
    # Al-Hussary a enregistré cinq lectures ; mp3quran les héberge toutes
    # sous le même identifiant « husr ». Vérifié le 20 août 2026.
    "hussary": {
        "nom": "Mahmoud Khalil Al-Hussary — Hafs (murattal)",
        "sourate": "https://server13.mp3quran.net/husr/{n:03d}.mp3",
        "verset": "https://everyayah.com/data/Husary_128kbps/{s:03d}{v:03d}.mp3",
    },
    "hussary-leger": {
        "nom": "Al-Hussary — Hafs, 64 kb/s (fichiers deux fois plus légers)",
        "sourate": None,
        "verset": "https://everyayah.com/data/Husary_64kbps/{s:03d}{v:03d}.mp3",
    },
    "hussary-mujawwad": {
        "nom": "Al-Hussary — Mujawwad (récitation lente et ornée)",
        "sourate": "https://server13.mp3quran.net/husr/Almusshaf-Al-Mojawwad/{n:03d}.mp3",
        "verset": "https://everyayah.com/data/Husary_Mujawwad_64kbps/{s:03d}{v:03d}.mp3",
    },
    "hussary-muallim": {
        "nom": "Al-Hussary — Mu'allim (verset répété, pour apprendre)",
        "sourate": None,
        "verset": "https://everyayah.com/data/Husary_Muallim_128kbps/{s:03d}{v:03d}.mp3",
    },
    "hussary-warsh": {
        "nom": "Al-Hussary — lecture Warsh 'an Nafi'",
        "sourate": "https://server13.mp3quran.net/husr/Rewayat-Warsh-A-n-Nafi/{n:03d}.mp3",
        "verset": None,
    },
    "hussary-qalon": {
        "nom": "Al-Hussary — lecture Qalon 'an Nafi'",
        "sourate": "https://server13.mp3quran.net/husr/Rewayat-Qalon-A-n-Nafi/{n:03d}.mp3",
        "verset": None,
    },
    "hussary-douri": {
        "nom": "Al-Hussary — lecture Ad-Douri 'an Abi Amr",
        "sourate": "https://server13.mp3quran.net/husr/Rewayat-Aldori-A-n-Abi-Amr/{n:03d}.mp3",
        "verset": None,
    },
    "abdulbasit": {
        "nom": "Abdul Basit Abdus Samad — Murattal",
        "sourate": "https://server7.mp3quran.net/basit/{n:03d}.mp3",
        "verset": "https://everyayah.com/data/Abdul_Basit_Murattal_64kbps/{s:03d}{v:03d}.mp3",
    },
    "minshawi": {
        "nom": "Mohamed Siddiq Al-Minshawi — Murattal",
        "sourate": "https://server10.mp3quran.net/minsh/{n:03d}.mp3",
        "verset": "https://everyayah.com/data/Minshawy_Murattal_128kbps/{s:03d}{v:03d}.mp3",
    },
    "sudais": {
        "nom": "Abdurrahman As-Sudais",
        "sourate": "https://server11.mp3quran.net/sds/{n:03d}.mp3",
        "verset": "https://everyayah.com/data/Abdurrahmaan_As-Sudais_192kbps/{s:03d}{v:03d}.mp3",
    },
    "shuraim": {
        "nom": "Saoud Ash-Shuraim",
        "sourate": "https://server7.mp3quran.net/shur/{n:03d}.mp3",
        "verset": "https://everyayah.com/data/Saood_ash-Shuraym_128kbps/{s:03d}{v:03d}.mp3",
    },
    "afasy": {
        "nom": "Mishary Rashid Al-Afasy",
        "sourate": "https://server8.mp3quran.net/afs/{n:03d}.mp3",
        "verset": "https://everyayah.com/data/Alafasy_128kbps/{s:03d}{v:03d}.mp3",
    },
}


def tester_url(url: str) -> tuple:
    """Vérifie qu'une adresse répond, sans télécharger le fichier."""
    try:
        requete = urllib.request.Request(
            url, headers={"User-Agent": NAVIGATEUR}, method="HEAD"
        )
        with urllib.request.urlopen(requete, timeout=15) as r:
            return True, int(r.headers.get("Content-Length") or 0)
    except urllib.error.HTTPError as e:
        # Certains serveurs refusent HEAD mais acceptent GET.
        if e.code in (403, 405, 501):
            try:
                with ouvrir(url) as r:
                    r.read(1)
                    return True, int(r.headers.get("Content-Length") or 0)
            except Exception:
                return False, 0
        return False, 0
    except Exception:
        return False, 0


def commande_coran(args) -> None:
    if args.lister:
        titre("Récitations disponibles")
        for cle, r in RECITATIONS.items():
            modes = []
            if r["sourate"]:
                modes.append("sourate")
            if r["verset"]:
                modes.append("verset")
            print(f"  {jaune(cle.ljust(20))} {r['nom']}")
            print(gris(f"  {' ' * 20} modes : {', '.join(modes)}"))
        return

    recitation = RECITATIONS.get(args.recitation)
    if not recitation:
        print(rouge(f"  Récitation inconnue : {args.recitation}"))
        print(gris("  Voir la liste :  python filet.py coran --lister"))
        raise SystemExit(2)

    gabarit = recitation[args.mode]
    if not gabarit:
        print(rouge(f"  « {args.recitation} » n'existe pas en mode {args.mode}."))
        autre = "verset" if args.mode == "sourate" else "sourate"
        if recitation[autre]:
            print(gris(f"  Essayez : --mode {autre}"))
        raise SystemExit(2)

    # Quelles sourates ?
    numeros = analyser_plage(args.sourates) if args.sourates else list(range(1, 115))

    titre(recitation["nom"])
    print(f"  Mode        : {args.mode}")
    print(f"  Sourates    : {len(numeros)} "
          f"({'toutes' if len(numeros) == 114 else args.sourates})")
    print(f"  Destination : {os.path.abspath(args.dossier)}")
    print(f"  Fils        : {args.fils}")

    # On vérifie une seule adresse avant de se lancer : si la source a bougé,
    # autant le savoir maintenant plutôt qu'après 6 000 échecs.
    sonde = gabarit.format(n=1, s=1, v=1)
    print()
    print(gris(f"  Vérification de la source… {sonde}"))
    ok, taille = tester_url(sonde)
    if not ok:
        print(rouge("  Cette source ne répond pas."))
        print(gris("  Les hébergeurs de récitations changent parfois d'adresse."))
        print(gris("  Vous pouvez indiquer la vôtre :"))
        print(gris("     python filet.py coran --gabarit "
                   "\"https://exemple.com/{n:03d}.mp3\" --mode sourate"))
        raise SystemExit(1)
    print(vert(f"  Source en ligne ({poids(taille)} pour le premier fichier)."))

    # Construction de la liste
    taches = []
    if args.mode == "sourate":
        for n in numeros:
            nom = f"{n:03d} - {SOURATES[n - 1]}.mp3"
            taches.append(Tache(
                url=gabarit.format(n=n),
                destination=os.path.join(args.dossier, nom_propre(nom)),
                etiquette=nom,
            ))
        estimation = len(taches) * (taille or 5_000_000)
    else:
        for n in numeros:
            sous_dossier = os.path.join(
                args.dossier, nom_propre(f"{n:03d} - {SOURATES[n - 1]}")
            )
            for v in range(1, VERSETS[n - 1] + 1):
                nom = f"{n:03d}{v:03d}.mp3"
                taches.append(Tache(
                    url=gabarit.format(s=n, v=v),
                    destination=os.path.join(sous_dossier, nom),
                    etiquette=f"{SOURATES[n - 1]} {v}",
                ))
        estimation = len(taches) * (taille or 180_000)

    print()
    print(f"  {len(taches)} fichiers · environ {poids(estimation)} au total")

    if not args.oui:
        reponse = input("  Lancer le téléchargement ? [O/n] ").strip().lower()
        if reponse and reponse[0] not in "oy":
            print(gris("  Annulé."))
            return

    titre("Téléchargement")
    bilan = lancer_lot(taches, args.fils)
    resumer(bilan, args.dossier)


def analyser_plage(texte: str, maxi: int = 114, quoi: str = "114 sourates") -> list:
    """« 1,3,36-40,112-114 » → [1, 3, 36, 37, 38, 39, 40, 112, 113, 114]"""
    numeros = set()
    for morceau in texte.split(","):
        morceau = morceau.strip()
        if not morceau:
            continue
        if "-" in morceau:
            a, _, b = morceau.partition("-")
            try:
                debut, fin = int(a), int(b)
            except ValueError:
                raise SystemExit(rouge(f"  Plage illisible : « {morceau} »"))
            numeros.update(range(min(debut, fin), max(debut, fin) + 1))
        else:
            try:
                numeros.add(int(morceau))
            except ValueError:
                raise SystemExit(rouge(f"  Numéro illisible : « {morceau} »"))
    hors = [n for n in numeros if not 1 <= n <= maxi]
    if hors:
        raise SystemExit(rouge(f"  Hors des {quoi} : {sorted(hors)}"))
    return sorted(numeros)


# ═══════════════════════════════════════════════════════════════════════
#  MODE PAGE — récupérer les audios d'une page web
# ═══════════════════════════════════════════════════════════════════════

EXT_AUDIO = (
    ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".flac",
    ".m4b", ".wma", ".amr", ".aiff", ".aif", ".mka", ".ac3", ".weba",
)
EXT_FLUX = (".m3u8", ".mpd")

# Attributs où une adresse de média peut se cacher. Les sites en inventent
# sans arrêt de nouveaux : la liste ratisse large, le tri se fait après.
ATTRS_URL = (
    "src", "href", "content", "value", "data-src", "data-url", "data-file",
    "data-mp3", "data-audio", "data-track", "data-source", "data-media",
    "data-link", "data-download", "data-stream", "data-original",
)
# Attributs qui portent souvent un nom lisible pour l'humain.
ATTRS_NOM = (
    "title", "data-title", "aria-label", "alt", "data-name",
    "data-artist", "data-song", "download",
)
# Indices qu'un lien sans extension mène quand même à un fichier.
INDICES = (
    "download", "telecharger", "télécharger", "audio", "mp3", "listen",
    "ecouter", "écouter", "media", "stream", "track", "sound", "recite",
    "sourate", "surah", "verset", "ayah", "episode", "podcast",
)

_DESECHAPPE = (("\\/", "/"), ("\\u002F", "/"), ("\\u002f", "/"), ("&amp;", "&"))


def _desechapper(texte: str) -> str:
    """Les adresses écrites dans du JavaScript arrivent échappées."""
    for avant, apres in _DESECHAPPE:
        texte = texte.replace(avant, apres)
    return texte


def est_audio(url: str) -> bool:
    return urllib.parse.urlparse(url).path.lower().endswith(EXT_AUDIO)


def est_flux(url: str) -> bool:
    return urllib.parse.urlparse(url).path.lower().endswith(EXT_FLUX)


def meme_site(a: str, b: str) -> bool:
    ha = urllib.parse.urlparse(a).netloc.lower().removeprefix("www.")
    hb = urllib.parse.urlparse(b).netloc.lower().removeprefix("www.")
    return ha == hb


@dataclass
class Trouvaille:
    url: str
    nom: str = ""
    depuis: str = ""
    taille: int = 0
    mime: str = ""
    sur: bool = True          # l'extension annonce déjà un audio
    flux: bool = False        # m3u8 / mpd : à confier à yt-dlp


# ───────────────────────────────────────────────────────────────────────
#  Lecture d'une page
# ───────────────────────────────────────────────────────────────────────

class Fouille(HTMLParser):
    """Repère les médias et les liens internes d'une page HTML.

    On passe par un vrai analyseur plutôt que par des expressions
    régulières : c'est le seul moyen d'attraper le texte d'un lien, qui
    donne presque toujours un bien meilleur nom de fichier que l'adresse.
    """

    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.medias = []      # [(url, nom)]
        self.douteux = []     # [(url, nom)] — sans extension, à sonder
        self.liens = []       # pages du même site
        self._a = None        # lien <a> en cours
        self._script = False
        self.scripts = []

    # -- outils --
    def _absolu(self, valeur: str) -> str:
        try:
            return urllib.parse.urljoin(self.base, _desechapper(valeur.strip()))
        except Exception:
            return ""

    def _ranger(self, url: str, nom: str, douteux: bool = False) -> None:
        if not url.lower().startswith(("http://", "https://")):
            return
        url = url.split("#")[0]
        (self.douteux if douteux else self.medias).append((url, nom))

    # -- analyse --
    def handle_starttag(self, tag, attrs):
        a = {c.lower(): (v or "") for c, v in attrs}

        if tag == "script":
            self._script = True

        nom = next((a[c] for c in ATTRS_NOM if a.get(c)), "")

        for cle in ATTRS_URL:
            valeur = a.get(cle)
            if not valeur:
                continue
            url = self._absolu(valeur)
            if not url:
                continue
            if est_audio(url) or est_flux(url):
                self._ranger(url, nom)

        if tag == "a" and a.get("href"):
            url = self._absolu(a["href"])
            self._a = {"url": url, "nom": nom, "textes": []}
            if url and meme_site(url, self.base) and not est_audio(url):
                self.liens.append(url.split("#")[0])

    def handle_data(self, donnees):
        if self._script:
            self.scripts.append(donnees)
        elif self._a is not None:
            self._a["textes"].append(donnees)

    def handle_endtag(self, tag):
        if tag == "script":
            self._script = False
        elif tag == "a" and self._a:
            lien = self._a
            self._a = None
            texte = re.sub(r"\s+", " ", "".join(lien["textes"])).strip()
            nom = lien["nom"] or texte
            if not lien["url"]:
                return
            if est_audio(lien["url"]) or est_flux(lien["url"]):
                self._ranger(lien["url"], nom)
            else:
                # Un lien sans extension peut quand même livrer un fichier :
                # « /download/1234 » est très courant. On ne le sonde que
                # s'il en a l'air, pour ne pas marteler le serveur.
                piste = (lien["url"] + " " + nom).lower()
                if any(i in piste for i in INDICES):
                    self._ranger(lien["url"], nom, douteux=True)


def balayage_brut(page: str, base: str) -> list:
    """Rattrape les adresses écrites en dur dans du JavaScript."""
    texte = _desechapper(page)
    motif = re.compile(
        r'["\'(\s](https?://[^"\'()\s\\]+?\.(?:'
        + "|".join(e.lstrip(".") for e in EXT_AUDIO + EXT_FLUX)
        + r')(?:\?[^"\'()\s\\]*)?)["\')\s\\]', re.I)
    motif_relatif = re.compile(
        r'["\'](/[^"\'()\s\\]+?\.(?:'
        + "|".join(e.lstrip(".") for e in EXT_AUDIO)
        + r')(?:\?[^"\'()\s\\]*)?)["\']', re.I)

    sortie = []
    for m in motif.finditer(texte):
        sortie.append((m.group(1).split("#")[0], ""))
    for m in motif_relatif.finditer(texte):
        sortie.append((urllib.parse.urljoin(base, m.group(1)).split("#")[0], ""))
    return sortie


# ───────────────────────────────────────────────────────────────────────
#  Playlists
#
#  Beaucoup de sites n'écrivent aucune adresse de fichier dans leur HTML :
#  ils chargent une playlist en JavaScript. C'est le cas d'Assabile, qui
#  pointe vers un XSPF de plus de mille pistes — avec les titres. Savoir
#  lire ces listes vaut mieux que n'importe quelle astuce de découpage.
# ───────────────────────────────────────────────────────────────────────

RE_PLAYLIST_PARAM = re.compile(
    r'[?&][a-z_]*(?:xml|playlist|feed|list|source)[a-z_]*='
    r'([^&"\'\s<>]+\.(?:xspf|xml|m3u|rss|json|jspf))', re.I)
RE_PLAYLIST_URL = re.compile(
    r'["\'(\s]((?:https?://|/)[^"\'()\s<>]+?\.(?:xspf|m3u|jspf|rss))', re.I)
RE_PLAYLIST_LIEN = re.compile(
    r'<link[^>]+type=["\']application/(?:xspf\+xml|rss\+xml)["\'][^>]*'
    r'href=["\']([^"\']+)["\']', re.I)

CLES_URL = ("url", "file", "src", "mp3", "location", "stream", "audio",
            "link", "enclosure", "path", "media")
CLES_TITRE = ("title", "titre", "name", "nom", "label", "text", "song")


def reperer_playlists(page: str, base: str) -> list:
    """Adresses de playlists mentionnées dans une page."""
    texte = _desechapper(page)
    vues, sortie = set(), []
    for motif in (RE_PLAYLIST_PARAM, RE_PLAYLIST_URL, RE_PLAYLIST_LIEN):
        for m in motif.finditer(texte):
            url = urllib.parse.urljoin(base, html.unescape(m.group(1)))
            if url in vues:
                continue
            # Le manifeste d'icônes d'un site n'est pas une playlist.
            if re.search(r"(manifest|favicon|sitemap|package)\.json$", url, re.I):
                continue
            vues.add(url)
            sortie.append(url)
    return sortie


def _local(balise: str) -> str:
    """« {ns}track » → « track »."""
    return balise.rsplit("}", 1)[-1].lower()


def _elaguer(contenu: str) -> str:
    """Coupe ce qui traîne après la fin du document.

    Des hébergeurs — Cloudflare en tête — injectent un `<script>` de suivi
    à la fin de CHAQUE réponse, y compris les XML et les JSON. Un analyseur
    strict refuse alors tout le fichier pour quelques octets parasites.
    """
    depart = contenu.lstrip()[:1]
    if depart in "{[":
        fin = max(contenu.rfind("}"), contenu.rfind("]"))
        return contenu[:fin + 1] if fin != -1 else contenu

    m = re.search(r"<([A-Za-z_][\w.-]*)", contenu)
    if not m:
        return contenu
    fin = contenu.rfind("</" + m.group(1))
    if fin == -1:
        return contenu
    ferme = contenu.find(">", fin)
    return contenu[:ferme + 1] if ferme != -1 else contenu


def _lire_xml(contenu: str, base: str) -> list:
    """Lit un XSPF ou un flux RSS de podcast."""
    import xml.etree.ElementTree as ET
    racine = None
    for essai in (contenu, _elaguer(contenu)):
        try:
            racine = ET.fromstring(essai)
            break
        except Exception:
            continue
    if racine is None:
        return []

    sortie = []
    for element in racine.iter():
        if _local(element.tag) not in ("track", "item", "entry"):
            continue
        url, titre = "", ""
        for enfant in element.iter():
            nom = _local(enfant.tag)
            if not url:
                if nom == "enclosure":
                    url = enfant.attrib.get("url", "")
                elif nom in ("location", "url", "link", "identifier") and enfant.text:
                    valeur = enfant.text.strip()
                    if est_audio(valeur) or valeur.startswith("http"):
                        url = valeur
            if not titre and nom == "title" and enfant.text:
                titre = enfant.text.strip()
        if url:
            sortie.append((urllib.parse.urljoin(base, url), titre))
    return sortie


def _lire_m3u(contenu: str, base: str) -> list:
    sortie, titre = [], ""
    for ligne in contenu.splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        if ligne.startswith("#EXTINF"):
            _, _, reste = ligne.partition(",")
            titre = reste.strip()
        elif not ligne.startswith("#"):
            sortie.append((urllib.parse.urljoin(base, ligne), titre))
            titre = ""
    return sortie


def _lire_json(contenu: str, base: str) -> list:
    donnees = None
    for essai in (contenu, _elaguer(contenu)):
        try:
            donnees = json.loads(essai)
            break
        except Exception:
            continue
    if donnees is None:
        return []

    sortie = []

    def parcourir(noeud):
        if isinstance(noeud, list):
            for x in noeud:
                parcourir(x)
        elif isinstance(noeud, dict):
            url = ""
            for cle in CLES_URL:
                valeur = noeud.get(cle)
                if isinstance(valeur, str) and (est_audio(valeur) or est_flux(valeur)):
                    url = valeur
                    break
                if isinstance(valeur, dict):          # enclosure imbriquée
                    for sous in CLES_URL:
                        v2 = valeur.get(sous)
                        if isinstance(v2, str) and est_audio(v2):
                            url = v2
                            break
                if url:
                    break
            if url:
                titre = next((noeud[c] for c in CLES_TITRE
                              if isinstance(noeud.get(c), str)), "")
                sortie.append((urllib.parse.urljoin(base, url), titre))
            for valeur in noeud.values():
                if isinstance(valeur, (list, dict)):
                    parcourir(valeur)

    parcourir(donnees)
    return sortie


def lire_playlist(url: str, referer: str = "") -> list:
    """Renvoie [(url, titre)] pour une playlist XSPF, RSS, M3U ou JSON."""
    try:
        with ouvrir(url, referer=referer) as reponse:
            brut = reponse.read(24 * 1024 * 1024)
            final = reponse.geturl()
    except Exception:
        return []

    contenu = brut.decode("utf-8", errors="replace").lstrip("﻿ \t\r\n")
    if contenu.startswith("#EXTM3U") or contenu.startswith("#EXTINF"):
        pistes = _lire_m3u(contenu, final)
    elif contenu[:1] in "{[":
        pistes = _lire_json(contenu, final)
    elif contenu[:1] == "<":
        pistes = _lire_xml(contenu, final)
    else:
        pistes = _lire_m3u(contenu, final)

    return [(u.split("#")[0], t) for u, t in pistes
            if u.lower().startswith(("http://", "https://")) and est_audio(u)]


def recuperer_page(url: str) -> tuple:
    """Renvoie (texte, url_finale) ou (None, url) si ce n'est pas du HTML."""
    try:
        with ouvrir(url) as reponse:
            type_contenu = (reponse.headers.get("Content-Type") or "").lower()
            if "html" not in type_contenu and "xml" not in type_contenu:
                return None, reponse.geturl()
            brut = reponse.read(8 * 1024 * 1024)          # 8 Mo suffisent
            final = reponse.geturl()
        jeu = "utf-8"
        m = re.search(r"charset=([\w-]+)", type_contenu)
        if m:
            jeu = m.group(1)
        return brut.decode(jeu, errors="replace"), final
    except Exception:
        return None, url


# ───────────────────────────────────────────────────────────────────────
#  Exploration
# ───────────────────────────────────────────────────────────────────────

def explorer(depart: str, profond: int, max_pages: int, filtre: str,
             pause: float = 0.2) -> tuple:
    """Parcourt le site à partir d'une page et rassemble tous les audios.

    Renvoie (trouvailles, pages_lues). Les doublons d'adresse sont écartés,
    mais le premier nom rencontré — souvent le texte du lien — est conservé.
    """
    motif = re.compile(filtre, re.I) if filtre else None
    vues, attente = set(), [(depart, 0)]
    par_url, ordre = {}, []
    pages_lues = 0
    playlists_vues = set()
    playlists_lues = 0
    MAX_PLAYLISTS = 8

    while attente and pages_lues < max_pages:
        url, niveau = attente.pop(0)
        if url in vues:
            continue
        vues.add(url)

        page, final = recuperer_page(url)
        if page is None:
            continue
        pages_lues += 1

        sys.stdout.write(
            f"\r  page {pages_lues}/{max_pages} · {len(ordre)} audios · "
            f"{urllib.parse.urlparse(url).path[:52] or '/'}          ")
        sys.stdout.flush()

        f = Fouille(final)
        try:
            f.feed(page)
            f.close()
        except Exception:
            pass                                   # HTML abîmé : on garde l'acquis

        recolte = [(u, n, False) for u, n in f.medias]
        recolte += [(u, n, False) for u, n in balayage_brut(page, final)]
        recolte += [(u, n, True) for u, n in f.douteux]

        # Une playlist vaut mille liens : c'est souvent le seul endroit où
        # le site écrit noir sur blanc l'adresse de ses fichiers.
        for adresse in reperer_playlists(page, final):
            if playlists_lues >= MAX_PLAYLISTS or adresse in playlists_vues:
                continue
            playlists_vues.add(adresse)
            sys.stdout.write(
                f"\r  playlist : {adresse.rsplit('/', 1)[-1][:48]}          ")
            sys.stdout.flush()
            pistes = lire_playlist(adresse, referer=final)
            if pistes:
                playlists_lues += 1
                recolte += [(u, n, False) for u, n in pistes]

        for u, n, douteux in recolte:
            if u in par_url:
                if n and not par_url[u].nom:
                    par_url[u].nom = n
                continue
            t = Trouvaille(url=u, nom=n, depuis=final,
                           sur=not douteux, flux=est_flux(u))
            par_url[u] = t
            ordre.append(t)

        if niveau < profond:
            for lien in f.liens:
                if lien in vues:
                    continue
                if motif and not motif.search(lien):
                    continue
                attente.append((lien, niveau + 1))

        if pause:
            time.sleep(pause)

    sys.stdout.write("\r" + " " * 100 + "\r")
    return ordre, pages_lues


# ───────────────────────────────────────────────────────────────────────
#  Mesure
# ───────────────────────────────────────────────────────────────────────

def mesurer(trouvailles: list, fils: int) -> None:
    """Interroge chaque adresse pour connaître son poids et son type."""
    total = len(trouvailles)
    if not total:
        return

    file = queue.Queue()
    for t in trouvailles:
        file.put(t)
    faits = [0]
    verrou = threading.Lock()

    def ouvrier():
        while True:
            try:
                t = file.get_nowait()
            except queue.Empty:
                return
            try:
                requete = urllib.request.Request(
                    t.url, headers={"User-Agent": NAVIGATEUR,
                                    "Referer": t.depuis}, method="HEAD")
                with urllib.request.urlopen(requete, timeout=20) as r:
                    t.taille = int(r.headers.get("Content-Length") or 0)
                    t.mime = (r.headers.get("Content-Type") or "").split(";")[0].lower()
                    depose = r.headers.get("Content-Disposition") or ""
                    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', depose)
                    if m and not t.nom:
                        t.nom = urllib.parse.unquote(m.group(1))
            except Exception:
                t.mime = t.mime or ""
            finally:
                with verrou:
                    faits[0] += 1
                file.task_done()

    # Une sonde HEAD ne transfère aucune donnée : l'essentiel du temps part
    # dans la poignée de main TLS. On peut donc en lancer beaucoup plus que
    # de téléchargements sans être impoli envers le serveur.
    equipe = [threading.Thread(target=ouvrier, daemon=True)
              for _ in range(max(2, min(fils * 4, 24)))]
    for f in equipe:
        f.start()
    while any(f.is_alive() for f in equipe):
        barre(faits[0], total, 0, 0)
        time.sleep(0.2)
    barre(total, total, 0, 0)
    print()


def dedoublonner(trouvailles: list) -> list:
    """Ne garde qu'un enregistrement par titre.

    Beaucoup de sites proposent la même sourate en plusieurs versions —
    Assabile en a plus de mille pour cent quatorze sourates. À titre égal
    on garde le fichier le plus lourd, c'est-à-dire le mieux encodé.
    """
    meilleurs, ordre = {}, []
    for t in trouvailles:
        cle = re.sub(r"\s+", " ", (t.nom or t.url).strip().lower())
        if cle not in meilleurs:
            meilleurs[cle] = t
            ordre.append(cle)
        elif t.taille > meilleurs[cle].taille:
            meilleurs[cle] = t
    return [meilleurs[c] for c in ordre]


def retenir(trouvailles: list) -> list:
    """Ne garde que ce qui est vraiment un fichier audio."""
    gardes = []
    for t in trouvailles:
        if t.flux:
            continue                                # traité à part
        if t.sur:
            gardes.append(t)                        # extension explicite
        elif t.mime.startswith("audio/") or t.mime in (
                "application/octet-stream", "binary/octet-stream"):
            gardes.append(t)                        # confirmé par le serveur
    return gardes


# ───────────────────────────────────────────────────────────────────────
#  Noms de sortie
# ───────────────────────────────────────────────────────────────────────

def extension_de(t: Trouvaille) -> str:
    chemin = urllib.parse.urlparse(t.url).path.lower()
    for e in EXT_AUDIO:
        if chemin.endswith(e):
            return e
    depuis_mime = {
        "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/mp4": ".m4a",
        "audio/aac": ".aac", "audio/ogg": ".ogg", "audio/opus": ".opus",
        "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/flac": ".flac",
        "audio/x-flac": ".flac", "audio/webm": ".weba",
    }
    return depuis_mime.get(t.mime, ".mp3")


def baptiser(trouvailles: list, numeroter: bool) -> None:
    """Attribue à chacun un nom de fichier unique et lisible."""
    pris = set()
    for n, t in enumerate(trouvailles, 1):
        base = t.nom.strip()
        if not base:
            base = urllib.parse.unquote(
                urllib.parse.urlparse(t.url).path.rsplit("/", 1)[-1])
        base = re.sub(r"\.(?:" + "|".join(e.lstrip(".") for e in EXT_AUDIO)
                      + r")$", "", base, flags=re.I)
        base = nom_propre(base, f"piste-{n:03d}")
        ext = extension_de(t)

        prefixe = f"{n:03d} - " if numeroter else ""
        candidat = f"{prefixe}{base}{ext}"
        suite = 2
        while candidat.lower() in pris:
            candidat = f"{prefixe}{base} ({suite}){ext}"
            suite += 1
        pris.add(candidat.lower())
        t.nom = candidat


# ───────────────────────────────────────────────────────────────────────
#  Inventaire et choix
# ───────────────────────────────────────────────────────────────────────

def inventaire(trouvailles: list, limite: int = 0) -> None:
    total = sum(t.taille for t in trouvailles)
    connus = sum(1 for t in trouvailles if t.taille)

    titre(f"{len(trouvailles)} audios trouvés")
    montres = trouvailles if not limite else trouvailles[:limite]
    for n, t in enumerate(montres, 1):
        poids_txt = poids(t.taille).rjust(9) if t.taille else gris("     ?   ")
        print(f"  {str(n).rjust(4)}  {t.nom[:62].ljust(62)} {poids_txt}")
    if limite and len(trouvailles) > limite:
        print(gris(f"        … et {len(trouvailles) - limite} autres "
                   f"(tapez « l » pour tout voir)"))

    print()
    if connus:
        estime = total if connus == len(trouvailles) else int(
            total / connus * len(trouvailles))
        mot = "au total" if connus == len(trouvailles) else "environ (estimation)"
        print(f"  Poids {mot} : {jaune(poids(estime))}")


def choisir(trouvailles: list, dossier: str) -> list:
    """Menu : tout prendre, une sélection, ou enregistrer la liste."""
    while True:
        print()
        print("  Que voulez-vous faire ?")
        print(f"    {jaune('[Entrée]')}   tout télécharger "
              f"({len(trouvailles)} fichiers)")
        print(f"    {jaune('1,5,10-20')}  télécharger cette sélection")
        print(f"    {jaune('l')}          revoir la liste complète")
        print(f"    {jaune('m')}          enregistrer la liste dans un fichier")
        print(f"    {jaune('q')}          quitter sans rien télécharger")
        try:
            reponse = input("  > ").strip()
        except EOFError:
            return trouvailles

        if reponse == "":
            return trouvailles
        bas = reponse.lower()
        if bas in ("q", "quitter", "n", "non"):
            return []
        if bas in ("l", "liste"):
            inventaire(trouvailles)
            continue
        if bas in ("m", "manifeste"):
            chemin = enregistrer_manifeste(trouvailles, dossier)
            print(vert(f"  Liste enregistrée : {chemin}"))
            print(gris(f"  Pour la reprendre : python filet.py liste \"{chemin}\""))
            continue
        if bas in ("t", "tout"):
            return trouvailles
        try:
            choix = analyser_plage(reponse, len(trouvailles),
                                   f"{len(trouvailles)} fichiers")
        except SystemExit as e:
            print(e)
            continue
        if choix:
            return [trouvailles[i - 1] for i in choix]


# ───────────────────────────────────────────────────────────────────────
#  Manifeste
# ───────────────────────────────────────────────────────────────────────

def enregistrer_manifeste(trouvailles: list, dossier: str) -> str:
    os.makedirs(dossier or ".", exist_ok=True)
    chemin = os.path.join(dossier or ".", "liste-filet.json")
    with open(chemin, "w", encoding="utf-8") as sortie:
        json.dump([{"url": t.url, "nom": t.nom, "taille": t.taille,
                    "mime": t.mime, "depuis": t.depuis} for t in trouvailles],
                  sortie, ensure_ascii=False, indent=1)
    return os.path.abspath(chemin)


def charger_manifeste(chemin: str) -> list:
    with open(chemin, encoding="utf-8") as entree:
        donnees = json.load(entree)
    return [Trouvaille(url=d["url"], nom=d.get("nom", ""),
                       taille=d.get("taille", 0), mime=d.get("mime", ""),
                       depuis=d.get("depuis", "")) for d in donnees]


# ───────────────────────────────────────────────────────────────────────
#  Commandes
# ───────────────────────────────────────────────────────────────────────

def _rapatrier(trouvailles: list, args) -> None:
    """Étape commune : choix, construction des tâches, téléchargement."""
    if args.montrer:
        return

    retenus = trouvailles if args.oui else choisir(trouvailles, args.dossier)
    if not retenus:
        print(gris("  Rien à faire."))
        return

    taches = [Tache(url=t.url,
                    destination=os.path.join(args.dossier, t.nom),
                    etiquette=t.nom,
                    taille=t.taille) for t in retenus]

    prevu = sum(t.taille for t in retenus)
    titre(f"Téléchargement — {len(taches)} fichiers"
          + (f", {poids(prevu)}" if prevu else ""))
    if prevu > 2 * 1024 ** 3:
        print(gris("  Gros volume : laissez tourner. Une coupure n'est pas "
                   "grave, la même commande reprendra où elle s'est arrêtée."))
        print()

    referer = trouvailles[0].depuis if trouvailles else ""
    bilan = lancer_lot(taches, args.fils, referer=referer, octets_prevus=prevu)
    resumer(bilan, args.dossier)


def commande_page(args) -> None:
    titre("Exploration")
    print(gris(f"  {args.url}"))
    print(gris(f"  profondeur {args.profond} · au plus {args.max_pages} pages"))
    print()

    trouvailles, pages = explorer(args.url, args.profond, args.max_pages,
                                  args.filtre, 0 if args.rapide else 0.2)

    fluxs = [t for t in trouvailles if t.flux]
    candidats = [t for t in trouvailles if not t.flux]
    surs = [t for t in candidats if t.sur]
    douteux = [t for t in candidats if not t.sur]

    print(f"  {pages} page(s) lue(s) · {len(surs)} audios certains"
          + (f" · {len(douteux)} liens à vérifier" if douteux else ""))

    # Les liens sans extension ne sont sondés que s'ils peuvent servir.
    a_sonder = list(surs)
    if douteux and (args.fouiller or not surs):
        print(gris(f"  Vérification de {len(douteux)} liens sans extension…"))
        a_sonder += douteux
    elif douteux:
        print(gris(f"  ({len(douteux)} liens sans extension ignorés — "
                   f"ajoutez --fouiller pour les vérifier)"))

    if not a_sonder:
        print()
        print(rouge("  Aucun audio trouvé."))
        print()
        print("  Pistes :")
        print("   · la page construit ses liens en JavaScript → "
              + jaune(f"python filet.py video {args.url}"))
        print("   · les audios sont sur des sous-pages → ajoutez "
              + jaune("--profond 2"))
        print("   · les liens n'ont pas d'extension → ajoutez "
              + jaune("--fouiller"))
        if fluxs:
            print(f"   · {len(fluxs)} flux (m3u8/mpd) repérés → "
                  + jaune("python filet.py video <url>"))
        raise SystemExit(1)

    print()
    if args.sans_mesure:
        print(gris("  Poids non mesurés (--sans-mesure)."))
        for t in a_sonder:
            t.sur = True                 # rien à confirmer, on fait confiance
    else:
        if len(a_sonder) > 300:
            print(gris(f"  Mesure de {len(a_sonder)} fichiers — comptez une à "
                       f"deux minutes. (--sans-mesure pour passer directement "
                       f"à la liste.)"))
        else:
            print(gris("  Mesure des fichiers…"))
        mesurer(a_sonder, args.fils)

    gardes = retenir(a_sonder)
    if args.min_mo:
        gardes = [t for t in gardes if t.taille >= args.min_mo * 1024 ** 2]
    if args.filtre_nom:
        m = re.compile(args.filtre_nom, re.I)
        gardes = [t for t in gardes if m.search(t.nom) or m.search(t.url)]

    if args.dedoublonner:
        avant = len(gardes)
        gardes = dedoublonner(gardes)
        if avant != len(gardes):
            print(gris(f"  Dédoublonnage par titre : {avant} → {len(gardes)} "
                       f"(la version la plus lourde a été gardée)"))

    if not gardes:
        print(rouge("  Rien ne subsiste après vérification."))
        raise SystemExit(1)

    baptiser(gardes, args.numeroter)
    inventaire(gardes, limite=0 if args.tout_voir else 40)

    if fluxs:
        print(gris(f"  ({len(fluxs)} flux m3u8/mpd mis de côté — "
                   f"utilisez « filet.py video » pour ceux-là)"))

    _rapatrier(gardes, args)


def commande_liste(args) -> None:
    if not os.path.exists(args.fichier):
        print(rouge(f"  Fichier introuvable : {args.fichier}"))
        raise SystemExit(1)
    trouvailles = charger_manifeste(args.fichier)
    titre(f"Liste rechargée — {len(trouvailles)} entrées")
    inventaire(trouvailles, limite=0 if args.tout_voir else 40)
    _rapatrier(trouvailles, args)


# ═══════════════════════════════════════════════════════════════════════
#  MODE VIDEO — délégué à yt-dlp
# ═══════════════════════════════════════════════════════════════════════

def commande_video(args) -> None:
    import shutil
    import subprocess

    outil = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if not outil:
        print(rouge("  yt-dlp n'est pas installé."))
        print()
        print("  Il gère YouTube, les playlists, les flux m3u8 et des")
        print("  milliers d'autres sites que ce script ne sait pas lire seul.")
        print()
        print(jaune("    pip install yt-dlp"))
        raise SystemExit(1)

    os.makedirs(args.dossier, exist_ok=True)
    gabarit = os.path.join(args.dossier, "%(playlist_index|)s%(playlist_index& - |)s%(title)s.%(ext)s")

    commande = [outil, "--no-overwrites", "--continue", "--ignore-errors",
                "-o", gabarit]

    if args.audio:
        commande += ["-x", "--audio-format", args.format, "--audio-quality", "0",
                     "--embed-thumbnail", "--embed-metadata"]
    else:
        commande += ["-f", "bv*+ba/b", "--merge-output-format", "mp4"]

    commande.append(args.url)

    titre("yt-dlp")
    print(gris("  " + " ".join(commande)))
    print()
    try:
        code = subprocess.call(commande)
    except KeyboardInterrupt:
        print("\n" + jaune("  Interrompu. Relancez : yt-dlp reprend où il s'est arrêté."))
        raise SystemExit(130)

    print()
    if code == 0:
        print(vert("  Terminé.") + gris(f"  Dossier : {os.path.abspath(args.dossier)}"))
    else:
        print(jaune(f"  yt-dlp s'est arrêté avec le code {code}."))
        print(gris("  Certains éléments ont pu échouer ; relancez pour reprendre."))


# ═══════════════════════════════════════════════════════════════════════
#  Ligne de commande
# ═══════════════════════════════════════════════════════════════════════

def principal(argv=None) -> None:
    analyseur = argparse.ArgumentParser(
        prog="filet",
        description="FILET — téléchargeur de L'Atelier.",
        epilog="Exemples :\n"
               "  python filet.py coran\n"
               "  python filet.py coran --mode verset --sourates 78-114\n"
               "  python filet.py page https://exemple.com/recitations\n"
               "  python filet.py page https://exemple.com --profond 2 --fouiller\n"
               "  python filet.py liste Telechargements/liste-filet.json\n"
               "  python filet.py video https://youtu.be/xxxx --audio\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sous = analyseur.add_subparsers(dest="commande")

    # --- coran ---
    c = sous.add_parser("coran", help="le Coran complet, par sourate ou par verset")
    c.add_argument("-r", "--recitation", default="hussary",
                   help="clé de la récitation (défaut : hussary)")
    c.add_argument("-m", "--mode", choices=["sourate", "verset"], default="sourate",
                   help="un fichier par sourate (114) ou par verset (6236)")
    c.add_argument("-s", "--sourates", default="",
                   help="sélection, ex. « 1,36,78-114 » (défaut : toutes)")
    c.add_argument("-d", "--dossier", default="Coran",
                   help="dossier de destination")
    c.add_argument("-f", "--fils", type=int, default=4,
                   help="téléchargements simultanés (défaut : 4)")
    c.add_argument("--gabarit", default="",
                   help="adresse personnalisée, ex. « https://x.com/{n:03d}.mp3 »")
    c.add_argument("--lister", action="store_true", help="lister les récitations")
    c.add_argument("-y", "--oui", action="store_true", help="ne pas demander confirmation")
    c.set_defaults(fonction=commande_coran)

    # --- page ---
    p = sous.add_parser(
        "page", help="explorer un site et récupérer ses audios",
        description="Analyse une page (et ses sous-pages si demandé), dresse "
                    "l'inventaire des audios trouvés avec leur poids, puis "
                    "vous laisse tout prendre ou choisir.")
    p.add_argument("url")
    p.add_argument("-d", "--dossier", default="Telechargements")
    p.add_argument("-f", "--fils", type=int, default=4,
                   help="téléchargements simultanés (défaut : 4)")
    p.add_argument("-p", "--profond", type=int, default=0, metavar="N",
                   help="suivre les liens du site sur N niveaux (défaut : 0)")
    p.add_argument("--max-pages", type=int, default=40, metavar="N",
                   help="plafond de pages à lire pendant l'exploration")
    p.add_argument("--filtre", default="", metavar="MOTIF",
                   help="n'explorer que les liens dont l'adresse contient ce motif")
    p.add_argument("--filtre-nom", default="", metavar="MOTIF",
                   help="ne garder que les audios dont le nom contient ce motif")
    p.add_argument("--fouiller", action="store_true",
                   help="vérifier aussi les liens sans extension "
                        "(« /download/1234 » et compagnie)")
    p.add_argument("--min-mo", type=float, default=0, metavar="N",
                   help="écarter les fichiers de moins de N Mo (jingles, bips)")
    p.add_argument("--dedoublonner", action="store_true",
                   help="un seul fichier par titre, le plus lourd "
                        "(utile quand un site propose dix versions du même titre)")
    p.add_argument("-n", "--numeroter", action="store_true",
                   help="préfixer les fichiers par leur rang")
    p.add_argument("--tout-voir", action="store_true",
                   help="afficher l'inventaire complet sans le tronquer")
    p.add_argument("--sans-mesure", action="store_true",
                   help="ne pas interroger le serveur sur le poids de chaque "
                        "fichier : inventaire immédiat, mais sans les tailles")
    p.add_argument("--rapide", action="store_true",
                   help="ne pas marquer de pause entre les pages explorées")
    p.add_argument("--montrer", action="store_true",
                   help="dresser l'inventaire sans rien télécharger")
    p.add_argument("-y", "--oui", action="store_true",
                   help="tout télécharger sans passer par le menu")
    p.set_defaults(fonction=commande_page)

    # --- liste ---
    l = sous.add_parser("liste",
                        help="reprendre un inventaire enregistré (liste-filet.json)")
    l.add_argument("fichier")
    l.add_argument("-d", "--dossier", default="Telechargements")
    l.add_argument("-f", "--fils", type=int, default=4)
    l.add_argument("--tout-voir", action="store_true")
    l.add_argument("--montrer", action="store_true")
    l.add_argument("-y", "--oui", action="store_true")
    l.set_defaults(fonction=commande_liste)

    # --- video ---
    v = sous.add_parser("video", help="YouTube et compagnie, via yt-dlp")
    v.add_argument("url")
    v.add_argument("-d", "--dossier", default="Telechargements")
    v.add_argument("-a", "--audio", action="store_true",
                   help="ne garder que le son")
    v.add_argument("--format", default="mp3",
                   help="format audio quand --audio est utilisé (défaut : mp3)")
    v.set_defaults(fonction=commande_video)

    args = analyseur.parse_args(argv)

    if not args.commande:
        analyseur.print_help()
        return

    # Gabarit personnalisé : il remplace la source de la récitation choisie.
    if getattr(args, "gabarit", ""):
        RECITATIONS["personnalise"] = {
            "nom": "Source personnalisée",
            "sourate": args.gabarit if args.mode == "sourate" else None,
            "verset": args.gabarit if args.mode == "verset" else None,
        }
        args.recitation = "personnalise"

    args.fonction(args)


if __name__ == "__main__":
    try:
        principal()
    except KeyboardInterrupt:
        print("\n" + jaune("  Interrompu."))
        raise SystemExit(130)
