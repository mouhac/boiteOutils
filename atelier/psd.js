/* =========================================================================
   L'ATELIER — lecture des calques d'un fichier Photoshop (.psd, .psb).

   Sans bibliothèque. On ne lit que ce qui sert à récupérer les pixels de
   chaque calque : le format complet est immense, la partie utile tient ici.

   Référence : « Adobe Photoshop File Formats Specification ».
   ========================================================================= */

/* Les calques qui n'ont pas de pixels à eux : leur contenu est calculé
   (texte, aplat de couleur, dégradé, réglage) ou n'est qu'un repère de groupe. */
const CLES_TEXTE = new Set(['TySh', 'tySh']);
const CLES_REMPLISSAGE = new Set(['SoCo', 'GdFl', 'PtFl', 'vscg']);
const CLES_REGLAGE = new Set([
  'levl', 'curv', 'brit', 'blnc', 'hue ', 'hue2', 'selc', 'thrs', 'nvrt', 'post',
  'mixr', 'grdm', 'phfl', 'expA', 'vibA', 'clrL', 'blwh', 'CgEd',
]);
const CLES_OBJET = new Set(['SoLd', 'PlLd', 'SoLE']);

/* En .psb, ces blocs ont une longueur sur 8 octets au lieu de 4. */
const CLES_LONGUES = new Set([
  'LMsk', 'Lr16', 'Lr32', 'Layr', 'Mt16', 'Mt32', 'Mtrn', 'Alph', 'FMsk',
  'lnk2', 'FEid', 'FXid', 'PxSD',
]);

const MODES = { 0: 'bitmap', 1: 'niveaux de gris', 2: 'couleurs indexées', 3: 'RVB',
                4: 'CMJN', 7: 'multicouche', 8: 'bichromie', 9: 'Lab' };

class Lecteur {
  constructor(tampon) {
    this.v = new DataView(tampon);
    this.o = new Uint8Array(tampon);
    this.p = 0;
  }
  u8()  { return this.v.getUint8(this.p++); }
  u16() { const n = this.v.getUint16(this.p); this.p += 2; return n; }
  i16() { const n = this.v.getInt16(this.p); this.p += 2; return n; }
  u32() { const n = this.v.getUint32(this.p); this.p += 4; return n; }
  i32() { const n = this.v.getInt32(this.p); this.p += 4; return n; }
  u64() { const h = this.u32(); return h * 2 ** 32 + this.u32(); }
  sig() { const s = String.fromCharCode(...this.o.subarray(this.p, this.p + 4)); this.p += 4; return s; }
  sauter(n) { this.p += n; }
}

/**
 * Ouvre un fichier Photoshop et liste ses calques, sans encore décoder les
 * pixels : on décode à la demande, un calque à la fois, pour ne pas tenir
 * cinquante images pleine page en mémoire.
 *
 * @param {ArrayBuffer} tampon
 * @returns {{largeur:number, hauteur:number, mode:string, calques:Array}}
 */
export function ouvrirPsd(tampon) {
  const L = new Lecteur(tampon);

  /* ---- En-tête ----------------------------------------------------- */
  if (L.sig() !== '8BPS') throw new Error('Ce n’est pas un fichier Photoshop.');
  const version = L.u16();
  if (version !== 1 && version !== 2) throw new Error('Version de Photoshop inconnue.');
  const psb = version === 2;
  L.sauter(6);
  const canauxImage = L.u16();               // canaux de l'image fusionnée
  const hauteur = L.u32();
  const largeur = L.u32();
  const profondeur = L.u16();
  const modeCode = L.u16();
  const mode = MODES[modeCode] || `mode ${modeCode}`;

  if (![1, 3, 4].includes(modeCode)) {
    throw new Error(`Fichier en ${mode} : seuls le RVB, le CMJN et les niveaux de gris sont pris en charge.`);
  }
  if (profondeur !== 8 && profondeur !== 16) {
    throw new Error(`Fichier en ${profondeur} bits par couche : seuls 8 et 16 bits sont pris en charge.`);
  }

  L.sauter(L.u32());                         // données de couleur (palette)
  L.sauter(L.u32());                         // ressources de l'image

  /* ---- Calques ----------------------------------------------------- */
  const longueur = () => (psb ? L.u64() : L.u32());
  const tailleSection = longueur();
  const finSection = L.p + tailleSection;    // l'image fusionnée commence ici
  const calques = [];
  const originaux = new Map();               // identifiant → fichier embarqué
  let transparenceFusion = false;

  const resultat = () => ({
    /**
     * Le fichier d'origine d'un objet dynamique (PNG, JPEG…), tel qu'il a
     * été placé dans Photoshop — ou null s'il n'y en a pas.
     */
    original: (calque) => (calque.lien && originaux.get(calque.lien)) || null,
    largeur, hauteur, mode, profondeur, calques,
    /** Pixels RVBA d'un calque, masque de fusion appliqué. */
    decoder: (calque) => decoderCalque(L.o, calque, { modeCode, profondeur, psb }),
    /**
     * L'image complète, telle que Photoshop l'affiche. Il l'enregistre à
     * côté des calques (option « compatibilité maximale », active par défaut).
     */
    decoderFusion: () => decoderFusion(L.o, finSection,
      { largeur, hauteur, canaux: canauxImage, modeCode, profondeur, psb, transparence: transparenceFusion }),
    /** Les plans de travail (recto, verso…), s'il y en a. */
    planches: calques.filter((c) => c.planche)
      .map((c) => ({ nom: c.nom, ...c.planche }))
      // Dans l'ordre de lecture : de gauche à droite, puis de haut en bas.
      .sort((a, b) => a.haut - b.haut || a.gauche - b.gauche),
  });

  if (!tailleSection) return resultat();
  const finInfos = longueur() + L.p;
  if (finInfos <= L.p) return resultat();
  const nombreBrut = L.i16();
  // Négatif : le premier canal en plus de l'image fusionnée est sa transparence.
  transparenceFusion = nombreBrut < 0;
  const nombre = Math.abs(nombreBrut);

  for (let i = 0; i < nombre; i++) {
    const c = { haut: L.i32(), gauche: L.i32() };
    c.bas = L.i32();
    c.droite = L.i32();
    c.canaux = [];
    const nbCanaux = L.u16();
    for (let k = 0; k < nbCanaux; k++) c.canaux.push({ id: L.i16(), taille: longueur() });

    L.sig();                                 // « 8BIM »
    c.fusion = L.sig();
    c.opacite = L.u8();
    L.u8();                                  // détourage
    const drapeaux = L.u8();
    c.cache = !!(drapeaux & 0x02);
    L.u8();

    const finExtra = L.u32() + L.p;

    /* Masque de fusion : on garde son cadre et sa couleur par défaut. */
    const tailleMasque = L.u32();
    if (tailleMasque) {
      const debut = L.p;
      c.masque = { haut: L.i32(), gauche: L.i32(), bas: L.i32(), droite: L.i32(),
                   defaut: L.u8(), drapeaux: L.u8() };
      L.p = debut + tailleMasque;
    }
    L.sauter(L.u32());                       // plages de fusion

    const lgNom = L.u8();
    c.nom = new TextDecoder('latin1').decode(L.o.subarray(L.p, L.p + lgNom));
    L.sauter(((lgNom + 1 + 3) & ~3) - 1);    // nom Pascal, aligné sur 4 octets

    /* Informations complémentaires : nature du calque, nom Unicode. */
    while (L.p + 12 <= finExtra) {
      const signature = L.sig();
      if (signature !== '8BIM' && signature !== '8B64') break;
      const cle = L.sig();
      const taille = psb && CLES_LONGUES.has(cle) ? L.u64() : L.u32();
      const debut = L.p;

      if (cle === 'luni') {
        const n = L.u32();
        let nom = '';
        for (let k = 0; k < n; k++) nom += String.fromCharCode(L.u16());
        c.nom = nom.replace(/\0+$/, '') || c.nom;
      } else if (cle === 'lsct' || cle === 'lsdk') {
        c.groupe = L.u32();                  // 1, 2 : début de groupe · 3 : fin
      } else if (CLES_TEXTE.has(cle)) c.genre = 'texte';
      else if (CLES_REMPLISSAGE.has(cle)) c.genre = 'remplissage';
      else if (CLES_REGLAGE.has(cle)) c.genre = 'reglage';
      else if (CLES_OBJET.has(cle)) {
        c.objet = true;
        c.lien = c.lien || identifiantObjet(L.o, cle, debut, debut + taille);
      }
      else if (cle === 'artb' || cle === 'artd' || cle === 'abdd') {
        c.planche = cadrePlanche(L.o, debut, debut + taille) || c.planche;
      }

      L.p = debut + taille;
    }
    L.p = finExtra;

    if (c.groupe) c.genre = 'groupe';
    c.genre = c.genre || 'pixels';
    c.largeur = Math.max(0, c.droite - c.gauche);
    c.hauteur = Math.max(0, c.bas - c.haut);
    calques.push(c);
  }

  /* Les pixels suivent, canal après canal, dans l'ordre des fiches. */
  for (const c of calques) {
    for (const canal of c.canaux) {
      canal.debut = L.p;
      L.p += canal.taille;
    }
  }

  /* Après les calques : les fichiers d'origine des objets dynamiques.
     Une image placée dans Photoshop y est gardée entière, à sa pleine
     résolution, même si le flyer ne la montre qu'en vignette. */
  L.p = finInfos;
  if (L.p + 4 <= finSection) L.sauter(L.u32());   // masque global
  while (L.p + 12 <= finSection) {
    // Les blocs sont alignés sur 4 octets ; on rattrape le bourrage éventuel.
    let k = 0;
    while (k < 4 && !['8BIM', '8B64'].includes(String.fromCharCode(...L.o.subarray(L.p, L.p + 4)))) { L.p++; k++; }
    if (k === 4) break;
    L.sig();
    const cle = L.sig();
    const taille = psb && CLES_LONGUES.has(cle) ? L.u64() : L.u32();
    const debut = L.p;
    if (cle === 'lnk2' || cle === 'lnk3' || cle === 'lnkD') lireOriginaux(L.o, debut, debut + taille, originaux);
    L.p = debut + taille;
  }

  /* Les noms de groupe donnent du contexte : on les rattache à chaque calque.
     Le fichier va du bas vers le haut ; en le lisant à l'envers, l'ouverture
     d'un groupe (qui porte son nom) précède son contenu. */
  const chemin = [];
  for (let i = calques.length - 1; i >= 0; i--) {
    const c = calques[i];
    if (c.groupe === 1 || c.groupe === 2) chemin.push(c.nom);
    else if (c.groupe === 3) chemin.pop();
    else c.dossier = chemin.join(' / ');
  }

  return resultat();
}

/**
 * Le cadre d'un plan de travail est rangé dans un « descripteur » Photoshop,
 * un format riche qu'on ne décode pas en entier : on y cherche seulement les
 * quatre côtés de « artboardRect », écrits « Top  doub <nombre> », etc.
 */
function cadrePlanche(octets, debut, fin) {
  const v = new DataView(octets.buffer, octets.byteOffset);
  const lire = (cle) => {
    const motif = [...cle, ...'doub'].map((ch) => ch.charCodeAt(0));
    for (let p = debut; p + 16 <= fin; p++) {
      let ok = true;
      for (let k = 0; k < 8 && ok; k++) ok = octets[p + k] === motif[k];
      if (ok) return v.getFloat64(p + 8);
    }
    return null;
  };
  const [haut, gauche, bas, droite] = ['Top ', 'Left', 'Btom', 'Rght'].map(lire);
  if ([haut, gauche, bas, droite].some((n) => n == null) || droite <= gauche || bas <= haut) return null;
  return { haut: Math.round(haut), gauche: Math.round(gauche),
           bas: Math.round(bas), droite: Math.round(droite) };
}

/* ------------------------------------------------------------------ */
/* Objets dynamiques : retrouver le fichier d'origine                  */
/* ------------------------------------------------------------------ */
const u32 = (o, p) => ((o[p] << 24) >>> 0) + (o[p + 1] << 16) + (o[p + 2] << 8) + o[p + 3];
const u64 = (o, p) => u32(o, p) * 2 ** 32 + u32(o, p + 4);
const egal = (o, p, motif) => motif.every((b, k) => o[p + k] === b);
const octetsDe = (s) => [...s].map((ch) => ch.charCodeAt(0));

/**
 * L'identifiant qui relie un calque à son fichier d'origine. « SoLd » le
 * range sous la clé « Idnt » de son descripteur ; « PlLd » le donne en clair,
 * juste après son en-tête.
 */
function identifiantObjet(o, cle, debut, fin) {
  if (cle === 'SoLd' || cle === 'SoLE') {
    const motif = octetsDe('IdntTEXT');
    for (let p = debut; p + 12 <= fin; p++) {
      if (!egal(o, p, motif)) continue;
      const n = u32(o, p + 8);
      let s = '';
      for (let k = 0; k < n; k++) s += String.fromCharCode((o[p + 12 + 2 * k] << 8) | o[p + 13 + 2 * k]);
      return s.replace(/\0+$/, '');
    }
  } else if (cle === 'PlLd') {
    const n = o[debut + 8];                   // après « plcL » et la version
    return String.fromCharCode(...o.subarray(debut + 9, debut + 9 + n));
  }
  return null;
}

/* Les formats d'image qu'un navigateur sait afficher, reconnus à leurs
   premiers octets. */
const SIGNATURES = [
  { type: 'image/png', ext: 'png', motif: [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A] },
  { type: 'image/jpeg', ext: 'jpg', motif: [0xFF, 0xD8, 0xFF] },
  { type: 'image/gif', ext: 'gif', motif: octetsDe('GIF8') },
  { type: 'image/webp', ext: 'webp', motif: octetsDe('RIFF') },
  { type: 'image/svg+xml', ext: 'svg', motif: octetsDe('<?xml') },
  { type: 'image/svg+xml', ext: 'svg', motif: octetsDe('<svg') },
  // Une photo placée comme « objet dynamique » est souvent elle-même un
  // document Photoshop : on le rouvrira avec ce même lecteur.
  { type: 'image/vnd.adobe.photoshop', ext: 'psd', motif: octetsDe('8BPS') },
];

/**
 * Le bloc « lnk2 » enchaîne les fichiers embarqués. Chacun a un en-tête
 * (identifiant, nom, taille), parfois suivi d'un descripteur qu'on ne décode
 * pas : on repère le début du fichier à sa signature, puis on prend
 * exactement le nombre d'octets annoncé.
 */
function lireOriginaux(o, debut, fin, originaux) {
  let p = debut;
  while (p + 8 <= fin) {
    const longueur = u64(o, p);
    const finEntree = p + 8 + longueur;
    if (!longueur || finEntree > fin) break;
    try {
      let q = p + 8;
      const genre = String.fromCharCode(...o.subarray(q, q + 4));
      q += 8;                                 // genre, version
      const lgId = o[q];
      const id = String.fromCharCode(...o.subarray(q + 1, q + 1 + lgId));
      q += 1 + lgId;
      const lgNom = u32(o, q);
      let nom = '';
      for (let k = 0; k < lgNom; k++) nom += String.fromCharCode((o[q + 4 + 2 * k] << 8) | o[q + 5 + 2 * k]);
      q += 4 + 2 * lgNom + 8;                 // nom, type et créateur de fichier
      const taille = u64(o, q);
      q += 8;

      if (genre === 'liFD' && taille > 0) {
        for (let s = q; s < finEntree - taille + 1; s++) {
          const sig = SIGNATURES.find((g) => egal(o, s, g.motif));
          if (!sig) continue;
          originaux.set(id, { nom: nom.replace(/\0+$/, ''), type: sig.type, ext: sig.ext,
                              octets: o.subarray(s, s + taille) });
          break;
        }
      }
    } catch { /* entrée illisible : on passe à la suivante */ }
    p = finEntree + ((4 - (longueur % 4)) % 4);   // entrées alignées sur 4 octets
  }
}

/** L'image fusionnée : tous ses canaux à la suite, d'un seul bloc. */
async function decoderFusion(octets, debut, { largeur: l, hauteur: h, canaux, modeCode, profondeur, psb, transparence }) {
  const compression = (octets[debut] << 8) | octets[debut + 1];
  const couleurs = modeCode === 4 ? 4 : modeCode === 3 ? 3 : 1;
  const avecAlpha = transparence && canaux > couleurs;
  const utiles = couleurs + (avecAlpha ? 1 : 0);
  const parLigne = l * (profondeur / 8);
  const plan = parLigne * h;
  let brut;

  if (compression === 0) {
    brut = octets.subarray(debut + 2, debut + 2 + plan * utiles);
  } else if (compression === 1) {
    // Une table de longueurs pour toutes les lignes de tous les canaux,
    // puis les données PackBits, canal après canal.
    brut = new Uint8Array(plan * utiles);
    depaqueter(octets, debut + 2 + canaux * h * (psb ? 4 : 2), octets.length, brut);
  } else {
    throw new Error('Image fusionnée compressée d’une façon non prise en charge.');
  }

  const canal = (k) => {
    const morceau = brut.subarray(k * plan, (k + 1) * plan);
    if (profondeur === 8) return morceau;
    const s = new Uint8Array(l * h);
    for (let i = 0; i < s.length; i++) s[i] = morceau[i * 2];
    return s;
  };

  const image = new ImageData(l, h);
  const d = image.data;
  const A = avecAlpha ? canal(couleurs) : null;
  if (modeCode === 4) {
    const [C, M, J, N] = [0, 1, 2, 3].map(canal);
    for (let i = 0, j = 0; j < l * h; i += 4, j++) {
      d[i] = (C[j] * N[j]) / 255;
      d[i + 1] = (M[j] * N[j]) / 255;
      d[i + 2] = (J[j] * N[j]) / 255;
      d[i + 3] = A ? A[j] : 255;
    }
  } else if (modeCode === 3) {
    const [R, V, B] = [0, 1, 2].map(canal);
    for (let i = 0, j = 0; j < l * h; i += 4, j++) {
      d[i] = R[j]; d[i + 1] = V[j]; d[i + 2] = B[j]; d[i + 3] = A ? A[j] : 255;
    }
  } else {
    const G = canal(0);
    for (let i = 0, j = 0; j < l * h; i += 4, j++) {
      d[i] = d[i + 1] = d[i + 2] = G[j]; d[i + 3] = A ? A[j] : 255;
    }
  }
  // Photoshop enregistre une image transparente « prémultipliée » sur du
  // blanc : on retire ce blanc pour que les bords détourés restent propres.
  if (A) {
    for (let i = 0; i < d.length; i += 4) {
      const a = d[i + 3];
      if (a === 0 || a === 255) continue;
      for (let k = 0; k < 3; k++) d[i + k] = Math.max(0, Math.min(255, (d[i + k] - 255 + a) * 255 / a));
    }
  }
  return image;
}

/** PackBits : un octet de contrôle, puis une série littérale ou répétée. */
function depaqueter(octets, p, fin, sortie) {
  let q = 0;
  while (q < sortie.length && p < fin) {
    const n = octets[p++];
    if (n < 128) {
      const k = n + 1;
      sortie.set(octets.subarray(p, p + k), q);
      p += k; q += k;
    } else if (n > 128) {
      const k = 257 - n;
      sortie.fill(octets[p++], q, q + k);
      q += k;
    }
  }
}

/* ------------------------------------------------------------------ */
/* Décodage des pixels                                                 */
/* ------------------------------------------------------------------ */
async function decoderCalque(octets, c, { modeCode, profondeur, psb }) {
  const l = c.largeur;
  const h = c.hauteur;
  const image = new ImageData(l, h);
  const d = image.data;
  const lire = (id, lg, ht) => {
    const canal = c.canaux.find((k) => k.id === id);
    return canal ? lireCanal(octets, canal, lg, ht, profondeur, psb) : null;
  };

  const alpha = await lire(-1, l, h);

  if (modeCode === 4) {
    // Photoshop range le CMJN inversé : 255 signifie « pas d'encre ».
    const [C, M, J, N] = await Promise.all([0, 1, 2, 3].map((k) => lire(k, l, h)));
    for (let i = 0, j = 0; j < l * h; i += 4, j++) {
      const n = N ? N[j] : 255;
      d[i]     = ((C ? C[j] : 255) * n) / 255;
      d[i + 1] = ((M ? M[j] : 255) * n) / 255;
      d[i + 2] = ((J ? J[j] : 255) * n) / 255;
      d[i + 3] = alpha ? alpha[j] : 255;
    }
  } else if (modeCode === 3) {
    const [R, V, B] = await Promise.all([0, 1, 2].map((k) => lire(k, l, h)));
    for (let i = 0, j = 0; j < l * h; i += 4, j++) {
      d[i] = R ? R[j] : 0;
      d[i + 1] = V ? V[j] : 0;
      d[i + 2] = B ? B[j] : 0;
      d[i + 3] = alpha ? alpha[j] : 255;
    }
  } else {
    const G = await lire(0, l, h);
    for (let i = 0, j = 0; j < l * h; i += 4, j++) {
      d[i] = d[i + 1] = d[i + 2] = G ? G[j] : 0;
      d[i + 3] = alpha ? alpha[j] : 255;
    }
  }

  /* Masque de fusion : ce que l'auteur a gommé doit redevenir transparent. */
  const m = c.masque;
  if (m && !(m.drapeaux & 0x02) && c.canaux.some((k) => k.id === -2)) {
    const ml = m.droite - m.gauche;
    const mh = m.bas - m.haut;
    const valeurs = ml > 0 && mh > 0 ? await lire(-2, ml, mh) : null;
    for (let y = 0; y < h; y++) {
      const my = y + c.haut - m.haut;
      for (let x = 0; x < l; x++) {
        const mx = x + c.gauche - m.gauche;
        const v = valeurs && mx >= 0 && my >= 0 && mx < ml && my < mh
          ? valeurs[my * ml + mx] : m.defaut;
        const i = (y * l + x) * 4 + 3;
        d[i] = (d[i] * v) / 255;
      }
    }
  }
  return image;
}

/** Un canal, décompressé, ramené à un octet par pixel. */
async function lireCanal(octets, canal, l, h, profondeur, psb) {
  const debut = canal.debut;
  const fin = debut + canal.taille;
  const compression = (octets[debut] << 8) | octets[debut + 1];
  const parLigne = l * (profondeur / 8);
  let brut;

  if (compression === 0) {
    brut = octets.subarray(debut + 2, debut + 2 + parLigne * h);
  } else if (compression === 1) {
    brut = new Uint8Array(parLigne * h);
    const tailleCompte = psb ? 4 : 2;
    // On saute la table des longueurs de ligne.
    depaqueter(octets, debut + 2 + h * tailleCompte, fin, brut);
  } else if (compression === 2 || compression === 3) {
    const flux = new Blob([octets.subarray(debut + 2, fin)]).stream()
      .pipeThrough(new DecompressionStream('deflate'));
    brut = new Uint8Array(await new Response(flux).arrayBuffer());
    if (compression === 3) {
      // Prédiction : chaque valeur est stockée en écart avec la précédente.
      const pas = profondeur / 8;
      for (let y = 0; y < h; y++) {
        const o = y * parLigne;
        if (pas === 1) {
          for (let x = 1; x < l; x++) brut[o + x] = (brut[o + x] + brut[o + x - 1]) & 0xFF;
        } else {
          let prec = (brut[o] << 8) | brut[o + 1];
          for (let x = 1; x < l; x++) {
            const v = (prec + ((brut[o + 2 * x] << 8) | brut[o + 2 * x + 1])) & 0xFFFF;
            brut[o + 2 * x] = v >> 8; brut[o + 2 * x + 1] = v & 0xFF;
            prec = v;
          }
        }
      }
    }
  } else {
    return null;
  }

  if (profondeur === 8) return brut;
  // 16 bits, gros-boutiste : l'octet de poids fort suffit pour un PNG 8 bits.
  const sortie = new Uint8Array(l * h);
  for (let i = 0; i < sortie.length; i++) sortie[i] = brut[i * 2];
  return sortie;
}
