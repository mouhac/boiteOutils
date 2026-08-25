#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests du moteur de fouille de FILET.

Aucune connexion internet requise : tout tourne sur des cas construits.
À lancer après chaque modification du scraper :

    python test_filet.py

Le but n'est pas de tester Assabile, mais les quatre façons dont les sites
du monde entier publient leurs audios : HTML, playlist XSPF, flux RSS de
podcast, playlist M3U ou JSON.
"""

import sys

import filet

_echecs = []


def verifier(nom, condition):
    if condition:
        print(f"  {filet.vert('OK')}    {nom}")
    else:
        print(f"  {filet.rouge('RATÉ')}  {nom}")
        _echecs.append(nom)


BASE = "https://exemple.com/page/"


# ═══════════════════════════════════════════════════════════════════════
def test_xspf():
    filet.titre("Playlist XSPF")
    # Cloudflare ajoute un <script> après la fin du document sur certains
    # hébergeurs : un analyseur strict refuserait tout le fichier.
    contenu = """<?xml version="1.0"?>
<playlist><trackList>
<track><location>https://cdn.ex.com/a.mp3</location><title>001 - Al-Fatiha</title></track>
<track><location>/relatif/b.m4a</location><title>Deuxième</title></track>
</trackList></playlist>
<script>(function(){window.__CF$cv$params={r:1}})()</script>"""
    r = filet._lire_xml(contenu, BASE)
    verifier(f"deux pistes malgré l'injection Cloudflare ({len(r)})", len(r) == 2)
    verifier("le titre du morceau est conservé", r and r[0][1] == "001 - Al-Fatiha")
    verifier("l'adresse relative est résolue",
             r and r[1][0] == "https://exemple.com/relatif/b.m4a")


def test_rss():
    filet.titre("Flux RSS de podcast")
    contenu = """<?xml version="1.0"?>
<rss xmlns:itunes="http://www.itunes.com/dtd" version="2.0"><channel>
<title>Le podcast</title>
<item><title>Épisode 1</title><enclosure url="https://cdn.ex.com/ep1.mp3" type="audio/mpeg"/></item>
<item><title>Épisode 2</title><enclosure url="https://cdn.ex.com/ep2.mp3" type="audio/mpeg"/></item>
</channel></rss>"""
    r = filet._lire_xml(contenu, BASE)
    verifier(f"deux épisodes trouvés ({len(r)})", len(r) == 2)
    verifier("le titre de l'épisode est lu", r and r[0][1] == "Épisode 1")
    verifier("l'espace de noms itunes ne gêne pas",
             r and r[1][0] == "https://cdn.ex.com/ep2.mp3")


def test_m3u():
    filet.titre("Playlist M3U")
    contenu = ("#EXTM3U\n#EXTINF:213,Sourate Ya-Sin\n"
               "https://cdn.ex.com/yasin.mp3\n#EXTINF:90,Court\n/c.ogg\n")
    r = filet._lire_m3u(contenu, BASE)
    verifier(f"deux pistes ({len(r)})", len(r) == 2)
    verifier("le titre vient de #EXTINF", r and r[0][1] == "Sourate Ya-Sin")


def test_json():
    filet.titre("Playlist JSON")
    contenu = ('{"data":{"tracks":['
               '{"title":"Un","file":"https://cdn.ex.com/1.mp3"},'
               '{"name":"Deux","url":"https://cdn.ex.com/2.opus"}]}}')
    r = filet._lire_json(contenu, BASE)
    verifier(f"deux pistes malgré l'imbrication ({len(r)})", len(r) == 2)
    verifier("les clés file/url et title/name sont reconnues",
             r and r[0][1] == "Un" and r[1][1] == "Deux")


def test_html():
    filet.titre("Extraction depuis le HTML")
    page = """<html><body>
<a href="/mp3/s36.mp3">Sourate Ya-Sin - Hussary</a>
<audio src="/mp3/s55.mp3" title="Ar-Rahman"></audio>
<div data-mp3="/mp3/s67.mp3" data-title="Al-Mulk"></div>
<a href="/download/9912">Télécharger la récitation</a>
<a href="/autre-page">Page normale</a>
<script>var p="https:\\/\\/cdn.ex.com\\/cache\\/s78.mp3";</script>
</body></html>"""
    f = filet.Fouille("https://exemple.com/")
    f.feed(page)
    f.close()
    noms = {u.rsplit("/", 1)[-1]: n for u, n in f.medias}
    brut = filet.balayage_brut(page, "https://exemple.com/")

    verifier("le texte du lien devient le nom du fichier",
             noms.get("s36.mp3") == "Sourate Ya-Sin - Hussary")
    verifier("l'attribut title d'une balise <audio> est lu",
             noms.get("s55.mp3") == "Ar-Rahman")
    verifier("data-mp3 et data-title sont lus",
             noms.get("s67.mp3") == "Al-Mulk")
    verifier("un lien /download/... est mis de côté pour vérification",
             any("9912" in u for u, _ in f.douteux))
    verifier("une page ordinaire n'est pas prise pour un audio",
             not any("autre-page" in u for u, _ in f.medias))
    verifier("une adresse échappée dans du JavaScript est rattrapée",
             any("s78.mp3" in u for u, _ in brut))


def test_playlists_reperees():
    filet.titre("Repérage des playlists")
    flash = ('<param value="autoplay=false&'
             'urlXML=/player/player-recitation-27.xml&color=#000">')
    pls = filet.reperer_playlists(flash, "https://fr.assabile.com/x/quran")
    verifier("playlist trouvée au milieu d'une chaîne de paramètres",
             pls and pls[0].endswith("/player/player-recitation-27.xml"))
    verifier("le manifeste d'icônes n'est pas pris pour une playlist",
             not filet.reperer_playlists('"/favicon/manifest.json"', BASE))
    lien = ('<link rel="alternate" type="application/rss+xml" '
            'href="/feed.xml">')
    verifier("flux RSS déclaré en <link> repéré",
             any(u.endswith("/feed.xml")
                 for u in filet.reperer_playlists(lien, BASE)))


def test_tri():
    filet.titre("Tri et nommage")
    T = filet.Trouvaille
    lot = [T(url="https://x/a.mp3", nom="001 - Al-Fatiha", taille=100),
           T(url="https://x/b.mp3", nom="001 - Al-Fatiha", taille=900),
           T(url="https://x/c.mp3", nom="002 - Al-Baqara", taille=50)]
    d = filet.dedoublonner(lot)
    verifier(f"trois entrées ramenées à deux ({len(d)})", len(d) == 2)
    verifier("à titre égal, le fichier le plus lourd est gardé",
             d[0].url == "https://x/b.mp3")

    doublons = [T(url="https://x/1.mp3", nom="Ya-Sin"),
                T(url="https://x/2.mp3", nom="Ya-Sin")]
    filet.baptiser(doublons, numeroter=False)
    verifier("deux titres identiques donnent deux fichiers distincts",
             doublons[0].nom != doublons[1].nom)

    numerotes = [T(url="https://x/1.mp3", nom="Ya-Sin")]
    filet.baptiser(numerotes, numeroter=True)
    verifier("l'option -n préfixe par le rang",
             numerotes[0].nom.startswith("001 - "))

    sale = [T(url="https://x/1.mp3", nom='Sourate: "Ya-Sin" / n°36')]
    filet.baptiser(sale, numeroter=False)
    verifier(f"les caractères interdits sont retirés ({sale[0].nom})",
             not any(c in sale[0].nom for c in '\\/:*?"<>|'))


def test_selection():
    filet.titre("Sélection par plage")
    verifier("« 1,5,10-12 » se déplie correctement",
             filet.analyser_plage("1,5,10-12", 20, "20 fichiers")
             == [1, 5, 10, 11, 12])
    try:
        filet.analyser_plage("1,99", 20, "20 fichiers")
        verifier("un numéro hors liste est refusé", False)
    except SystemExit:
        verifier("un numéro hors liste est refusé", True)


def test_coran():
    filet.titre("Tables du Coran")
    verifier("114 sourates", len(filet.SOURATES) == 114)
    verifier("6236 versets au total", sum(filet.VERSETS) == 6236)


# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    for essai in (test_xspf, test_rss, test_m3u, test_json, test_html,
                  test_playlists_reperees, test_tri, test_selection,
                  test_coran):
        essai()

    print()
    if _echecs:
        print(filet.rouge(f"  {len(_echecs)} test(s) en échec :"))
        for nom in _echecs:
            print(f"    · {nom}")
        sys.exit(1)
    print(filet.vert("  Tout passe."))
