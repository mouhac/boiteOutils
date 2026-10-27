# L'Atelier

Une boîte à outils personnelle : les manipulations de fichiers qu'on fait tout
le temps, sans passer par des sites couverts de publicités.

**Tout tourne dans le navigateur.** Aucun fichier n'est envoyé sur un serveur —
ce qui compte quand on manipule des pièces d'identité, des contrats ou des
photos de famille. Pas de compte, pas de limite de taille imposée, pas de
filigrane sur le résultat.

---

## Les outils

### Prêts

| Outil | Ce qu'il fait |
|---|---|
| **Chemise** | Assemble photos, scans et PDF en un seul dossier PDF. Cartes d'identité à taille réelle, planches contact, recto/verso, numérotation, traits de coupe. |
| **Presse** | Allège un PDF trop lourd. Trois niveaux de compression, conversion en niveaux de gris, livraison en PDF ou en JPG (archive ZIP pour plusieurs pages) avec le nom de votre choix. |
| **Tamis** | Extrait les photos de PDF et de fichiers Photoshop (PSD), à leur taille réelle. Bords vides retirés ; formes, ombres et textes colorés écartés. Depuis un PSD, chaque calque photo sort seul et détouré. Les JPEG intacts sont recopiés octet pour octet. Une archive ZIP avec un dossier par document. |
| **Poinçon** | QR codes présentables : Wi-Fi, contact vCard, lien, e-mail, SMS. Logo au centre, dégradés, formes de modules, export PNG haute définition et SVG. |
| **Sillon** | Extrait la piste audio d'une vidéo. Copie directe sans réencoder quand c'est possible : qualité identique, résultat quasi instantané. |
| **Alambic** | Convertit audio, vidéo et images. Les vocaux WhatsApp en MP3, une vidéo en MP4 lisible partout, un JPEG en PNG. Traitement en lot. |
| **Gomme** | Efface un texte, un pseudo ou un logo incrusté dans une vidéo. Reconstruction, flou, pixelisation ou recadrage, avec aperçu avant rendu. |
| **Filet** | *(compagnon Python)* Explore n'importe quel site, dresse l'inventaire des audios trouvés avec leur poids, puis télécharge tout ou une sélection. Sait aussi récupérer le Coran complet par sourate ou par verset, et déléguer à yt-dlp. |

### En chantier

Massicot (découper un PDF) · Paraphe (signer un PDF) · Filigrane · Loupe (OCR
français et arabe) · Cisaille (couper un extrait sans réencoder) · Presse
(alléger un fichier) · Soudure (coller plusieurs audios) · Plume (transcription
et sous-titres) · Détourage · Tirage · Établi texte

---

## Utilisation

### En ligne

Publiez le dépôt sur GitHub Pages (voir plus bas) et ouvrez l'adresse. C'est
tout : rien à installer.

### En local

Ouvrez `index.html` dans un navigateur. La plupart des outils fonctionnent
directement en double-cliquant le fichier.

Pour que **tous** les outils marchent, il faut un vrai serveur — les modules
JavaScript sont bloqués sur le protocole `file://`. Une ligne suffit :

```bash
python -m http.server 8000
```

Puis ouvrez `http://localhost:8000`.

### Le compagnon Python

```bash
cd compagnon
python filet.py --help
```

Le mode `page` est un vrai scraper : il lit le HTML, les attributs `data-*`,
le JavaScript, et surtout les **playlists** (XSPF, M3U, JSON, flux RSS de
podcast) — c'est là que la plupart des sites cachent réellement l'adresse de
leurs fichiers. Il dresse ensuite l'inventaire chiffré de ce qu'il a trouvé et
vous laisse tout prendre ou choisir :

```bash
python filet.py page https://exemple.com/recitations --dedoublonner
```

Le volume n'a pas d'importance : tout est repris là où ça s'est arrêté si la
connexion coupe. Détails complets dans `compagnon/index.html`.

---

## Publier sur GitHub Pages

```bash
git init
git add .
git commit -m "L'Atelier"
git branch -M main
git remote add origin https://github.com/VOTRE-COMPTE/atelier.git
git push -u origin main
```

Puis dans les réglages du dépôt : **Settings → Pages → Source: Deploy from a
branch → main / (root)**. L'adresse arrive en une minute.

Aucune configuration, aucune étape de compilation, aucune dépendance à
installer : le dépôt est le site.

---

## Comment c'est fait

HTML, CSS et JavaScript modernes. Pas de framework, pas de `npm`, pas d'étape de
build. Chaque outil est une page autonome ; elles partagent une feuille de style
et trois petits modules.

```
index.html               Accueil — la grille des outils
atelier/
  atelier.css            Le langage visuel commun
  outils.js              Le catalogue (source de vérité de l'accueil)
  ui.js                  Zone de dépôt, messages, formats, téléchargement
  moteur.js              ffmpeg.wasm partagé — chargement, exécution, analyse
  psd.js                 Lecture des calques Photoshop, sans bibliothèque (Tamis)
  vendor/                7 Ko de code tiers qui doit être servi en local
outils/
  chemise/  presse/  tamis/  poincon/  sillon/  alambic/  gomme/
compagnon/
  filet.py               Le téléchargeur
  index.html             Son mode d'emploi
```

### Les bibliothèques

Chargées depuis un CDN, au moment où elles servent :

- **pdf-lib** et **pdf.js** — lecture et écriture de PDF (Chemise, Presse, Tamis)
- **Sortable** — réorganisation par glisser-déposer (Chemise)
- **qr-code-styling** — rendu des QR codes (Poinçon)
- **ffmpeg.wasm** — audio et vidéo (Sillon, Alambic, Gomme)

Le moteur ffmpeg pèse environ 32 Mo. Il n'est téléchargé qu'au premier usage
d'un outil qui en a besoin, puis reste dans le cache du navigateur. Les images
et les PDF n'y touchent jamais.

---

## Ce qu'il faut savoir

**Les gros fichiers.** Un onglet plafonne autour de 2 Go de mémoire. Au-delà
d'une vidéo d'une heure, mieux vaut utiliser un vrai ffmpeg installé sur la
machine.

**La vitesse.** L'atelier utilise le moteur ffmpeg mono-cœur. La version
multi-cœurs est 2 à 4 fois plus rapide, mais elle exige des en-têtes HTTP
(`COOP`/`COEP`) qu'un hébergement statique ne permet pas de régler — et les
forcer casserait le chargement des polices et des bibliothèques. La fiabilité a
été préférée à la vitesse. Si vous hébergez un jour l'atelier derrière un
serveur qui envoie ces en-têtes, la bascule est automatique.

**Effacer un texte dans une vidéo.** La reconstruction (`delogo`) fait vraiment
disparaître une petite marque sur un fond calme. Un gros sous-titre au milieu de
l'image ne peut pas être retiré sans laisser de trace — ni ici, ni ailleurs :
ce qui est dessous n'a jamais été enregistré. Dans ce cas, recadrez ou floutez.

**Les vidéos en AV1** ne peuvent pas être réencodées ici : le moteur wasm n'a
pas de décodeur pour ce format, encore récent (on le rencontre surtout sur des
téléchargements YouTube et des enregistreurs d'écran modernes). L'atelier le
détecte et le dit clairement plutôt que d'échouer sur un code d'erreur. Le
changement de conteneur et l'extraction audio continuent de fonctionner, eux,
puisqu'ils ne décodent pas l'image. Si un autre format se révèle indécodable à
l'usage, ajoutez-le à `SANS_DECODEUR` dans `atelier/moteur.js` pour obtenir le
même message clair.

**Le HEIC des iPhone** n'est pas lisible par les navigateurs. Convertissez-le en
JPEG sur le téléphone avant de l'apporter ici.

---

## Ajouter un outil

1. Créer `outils/mon-outil/index.html`
2. Lier la feuille commune : `<link rel="stylesheet" href="../../atelier/atelier.css">`
3. Importer ce dont on a besoin : `import { $, dire, zoneDepot } from '../../atelier/ui.js'`
4. Ajouter une entrée dans `atelier/outils.js` — l'accueil se met à jour tout seul

Le gabarit d'une page d'outil se lit dans n'importe lequel des cinq existants :
un `<header class="bar">`, un `.shell` en deux colonnes (`.panel` pour les
réglages, `.mat` pour le plan de travail), un `.pied`.
