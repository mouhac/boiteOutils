/* =========================================================================
   L'ATELIER — catalogue des outils.

   Une seule source de vérité : la page d'accueil, les menus et le plan de
   route se construisent à partir de cette liste.

   etat : 'pret'    — utilisable
          'chantier'— prévu, pas encore construit
          'atelier' — passe par le compagnon Python (compagnon/)
   ========================================================================= */

const i = (d, opts = '') =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" ` +
  `stroke-linecap="round" stroke-linejoin="round" ${opts}>${d}</svg>`;

export const RAYONS = [
  { cle: 'documents', nom: 'Documents',    note: 'PDF, scans, pièces administratives' },
  { cle: 'media',     nom: 'Audio & vidéo', note: 'Convertir, extraire, découper, nettoyer' },
  { cle: 'images',    nom: 'Images',        note: 'Recadrer, détourer, alléger' },
  { cle: 'divers',    nom: 'Établi',        note: 'Le reste de la boîte' },
];

export const OUTILS = [
  /* ------------------------------ Documents ------------------------------ */
  {
    cle: 'chemise', rayon: 'documents', etat: 'pret',
    nom: 'Chemise',
    sous: 'Assembler photos, scans et PDF en un seul dossier',
    detail: 'Cartes d’identité à taille réelle, planches contact, recto/verso, ' +
            'numérotation et traits de coupe.',
    href: 'outils/chemise/',
    icone: i('<path d="M3 7h6l2 3h10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/><path d="M3 11h18"/>'),
  },
  {
    cle: 'signature', rayon: 'documents', etat: 'chantier',
    nom: 'Paraphe',
    sous: 'Signer et cacheter un PDF',
    detail: 'Poser une signature manuscrite, une date et un cachet, puis aplatir le document.',
    icone: i('<path d="M3 18c3-1 5-9 8-9s2 6 4 6 3-3 6-3"/><path d="M4 21h16"/>'),
  },
  {
    cle: 'filigrane', rayon: 'documents', etat: 'chantier',
    nom: 'Filigrane',
    sous: 'Marquer un PDF en travers',
    detail: '« COPIE », « CONFIDENTIEL », un logo ou un texte libre, sur toutes les pages.',
    icone: i('<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M7 16 17 8"/>'),
  },
  {
    cle: 'decoupe-pdf', rayon: 'documents', etat: 'chantier',
    nom: 'Massicot',
    sous: 'Extraire, réorganiser et pivoter des pages',
    detail: 'Séparer un scan en plusieurs fichiers, retirer des pages, corriger une orientation.',
    icone: i('<circle cx="6" cy="6" r="2.4"/><circle cx="6" cy="18" r="2.4"/><path d="M8 7.5 20 18M8 16.5 20 6"/>'),
  },
  {
    cle: 'loupe', rayon: 'documents', etat: 'chantier',
    nom: 'Loupe',
    sous: 'Lire le texte d’un scan ou d’une photo',
    detail: 'Reconnaissance de caractères en français et en arabe, PDF rendu cherchable.',
    icone: i('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/><path d="M8.5 9.5h5M8.5 12.5h3"/>'),
  },

  /* ---------------------------- Audio & vidéo ---------------------------- */
  {
    cle: 'sillon', rayon: 'media', etat: 'pret',
    nom: 'Sillon',
    sous: 'Extraire le son d’une vidéo',
    detail: 'MP3, M4A, WAV ou FLAC. Copie directe de la piste quand c’est possible : ' +
            'aucune perte de qualité, résultat quasi instantané.',
    href: 'outils/sillon/',
    icone: i('<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.2"/><circle cx="12" cy="12" r="5.6" opacity=".45"/>'),
  },
  {
    cle: 'alambic', rayon: 'media', etat: 'pret',
    nom: 'Alambic',
    sous: 'Convertir audio, vidéo et images',
    detail: 'Les vocaux WhatsApp (.opus) en MP3, une vidéo en MP4 lisible partout, ' +
            'un JPEG en PNG. Traitement en lot.',
    href: 'outils/alambic/',
    icone: i('<path d="M9 3v6L4 19a2 2 0 0 0 1.8 2h12.4A2 2 0 0 0 20 19l-5-10V3"/><path d="M8 3h8"/><path d="M6.5 14h11"/>'),
  },
  {
    cle: 'gomme', rayon: 'media', etat: 'pret',
    nom: 'Gomme',
    sous: 'Effacer un texte ou un logo dans une vidéo',
    detail: 'Reconstruction de la zone, flou, pixelisation ou recadrage. ' +
            'Sélection du cadre à la souris, directement sur l’image.',
    href: 'outils/gomme/',
    icone: i('<path d="M8.5 20H20"/><path d="m4.5 16.5 7-7a2 2 0 0 1 2.8 0l3.2 3.2a2 2 0 0 1 0 2.8L13 20H7l-2.5-2.5a1 1 0 0 1 0-1z"/>'),
  },
  {
    cle: 'cisaille', rayon: 'media', etat: 'chantier',
    nom: 'Cisaille',
    sous: 'Couper un extrait précis, sans réencoder',
    detail: 'On garde exactement les octets d’origine : instantané, qualité intacte.',
    icone: i('<circle cx="6" cy="7" r="2.2"/><circle cx="6" cy="17" r="2.2"/><path d="M8 8.2 19 17M8 15.8 19 7"/>'),
  },
  {
    cle: 'presse', rayon: 'media', etat: 'chantier',
    nom: 'Presse',
    sous: 'Alléger un fichier trop lourd',
    detail: 'Viser une taille en Mo (WhatsApp, pièce jointe) et laisser l’outil trouver les réglages.',
    icone: i('<path d="M4 4h16"/><path d="M4 20h16"/><path d="M8 8h8v8H8z"/><path d="M12 8V5M12 19v-3"/>'),
  },
  {
    cle: 'soudure', rayon: 'media', etat: 'chantier',
    nom: 'Soudure',
    sous: 'Coller plusieurs audios ou vidéos bout à bout',
    detail: 'Une sourate entière en un seul MP3, plusieurs rushes en une vidéo.',
    icone: i('<rect x="2" y="9" width="8" height="6" rx="1.5"/><rect x="14" y="9" width="8" height="6" rx="1.5"/><path d="M10 12h4"/>'),
  },
  {
    cle: 'plume', rayon: 'media', etat: 'chantier',
    nom: 'Plume',
    sous: 'Transcrire un audio en texte et en sous-titres',
    detail: 'Fichier .txt et .srt, horodatés. Français, anglais, arabe.',
    icone: i('<path d="M4 20c6-2 9-6 12-12l4-4-4 12c-4 3-8 4-12 4z"/><path d="M4 20 9 15"/>'),
  },
  {
    cle: 'filet', rayon: 'media', etat: 'atelier',
    nom: 'Filet',
    sous: 'Explorer un site et récupérer ses audios',
    detail: 'Dresse l’inventaire chiffré de tout ce qu’il trouve — HTML, lecteurs JavaScript, ' +
            'playlists XSPF et M3U, flux de podcast — puis vous laissez tout prendre ou choisir. ' +
            'Des gigaoctets si besoin, reprenable si la connexion coupe.',
    href: 'compagnon/',
    icone: i('<path d="M12 3v13"/><path d="m7 11 5 5 5-5"/><path d="M4 20h16"/>'),
  },

  /* -------------------------------- Images ------------------------------- */
  {
    cle: 'poincon', rayon: 'images', etat: 'pret',
    nom: 'Poinçon',
    sous: 'Frapper un QR code, en beau',
    detail: 'Wi-Fi, contact, lien, texte, e-mail. Logo au centre, dégradés, ' +
            'formes de modules, export PNG haute définition et SVG.',
    href: 'outils/poincon/',
    icone: i('<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3h-3zM20 14v3M14 20h6"/>'),
  },
  {
    cle: 'detourage', rayon: 'images', etat: 'chantier',
    nom: 'Détourage',
    sous: 'Enlever le fond d’une photo',
    detail: 'Sujet isolé sur fond transparent, sans abonnement et sans envoyer la photo ailleurs.',
    icone: i('<path d="M4 4h4M4 4v4M20 4h-4M20 4v4M4 20h4M4 20v-4M20 20h-4M20 20v-4"/><circle cx="12" cy="10" r="2.6"/><path d="M7.5 17c1-2.6 2.6-4 4.5-4s3.5 1.4 4.5 4"/>'),
  },
  {
    cle: 'tirage', rayon: 'images', etat: 'chantier',
    nom: 'Tirage',
    sous: 'Recadrer, redimensionner et filigraner en lot',
    detail: 'Formats réseaux sociaux prêts à l’emploi, traitement de tout un dossier d’un coup.',
    icone: i('<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.6"/><path d="m3 16 5-4 4 3 3-2 6 5"/>'),
  },

  /* -------------------------------- Établi ------------------------------- */
  {
    cle: 'etabli-texte', rayon: 'divers', etat: 'chantier',
    nom: 'Établi',
    sous: 'Nettoyer et reformater du texte',
    detail: 'Retours à la ligne parasites, casse, accents, comptage, mise en forme JSON et CSV.',
    icone: i('<path d="M4 6h16M4 12h11M4 18h14"/>'),
  },
];

/* ---------- Aides ---------- */

export const parEtat = (etat) => OUTILS.filter((o) => o.etat === etat);
export const parRayon = (rayon) => OUTILS.filter((o) => o.rayon === rayon);
export const trouver = (cle) => OUTILS.find((o) => o.cle === cle);

export const LIBELLE_ETAT = {
  pret:     { texte: 'Prêt',        couleur: 'var(--repere)' },
  chantier: { texte: 'En chantier', couleur: 'var(--craie-3)' },
  atelier:  { texte: 'Compagnon',   couleur: 'var(--reglet)' },
};
