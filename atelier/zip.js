/* =========================================================================
   L'ATELIER — fabrication d'archives ZIP, sans bibliothèque.

   Les entrées sont stockées telles quelles (méthode « store », sans
   compression). Ce n'est pas un manque : JPEG, PNG, MP3 et MP4 sont déjà
   compressés, les recompresser ne gagnerait rien et coûterait du temps.
   ========================================================================= */

/* ---------- CRC32 ---------- */

let table = null;

function tableCrc() {
  if (table) return table;
  table = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) {
      c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
    }
    table[i] = c >>> 0;
  }
  return table;
}

function crc32(donnees) {
  const t = tableCrc();
  let c = 0xFFFFFFFF;
  for (let i = 0; i < donnees.length; i++) {
    c = t[(c ^ donnees[i]) & 0xFF] ^ (c >>> 8);
  }
  return (c ^ 0xFFFFFFFF) >>> 0;
}

/* ---------- Date au format MS-DOS ---------- */

function horodateDos(date = new Date()) {
  const annee = Math.max(1980, date.getFullYear());
  return {
    heure: (date.getHours() << 11) | (date.getMinutes() << 5)
           | (Math.floor(date.getSeconds() / 2)),
    date: ((annee - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate(),
  };
}

/* ---------- Assemblage ---------- */

const LIMITE = 0xFFFFFFFF;   // au-delà, il faudrait le format ZIP64

/**
 * Fabrique une archive ZIP.
 *
 * @param {Array<{nom:string, donnees:Uint8Array|ArrayBuffer|Blob}>} entrees
 * @param {Date} [date] horodatage appliqué à toutes les entrées
 * @returns {Promise<Blob>}
 */
export async function creerZip(entrees, date = new Date()) {
  if (!entrees?.length) throw new Error('Archive vide : rien à mettre dedans.');
  if (entrees.length > 0xFFFF) {
    throw new Error('Plus de 65 535 fichiers : au-delà, il faudrait le format ZIP64.');
  }

  const encodeur = new TextEncoder();
  const { heure, date: jour } = horodateDos(date);

  const preparees = [];
  const nomsPris = new Set();

  for (const entree of entrees) {
    let donnees = entree.donnees;
    if (donnees instanceof Blob) donnees = new Uint8Array(await donnees.arrayBuffer());
    else if (donnees instanceof ArrayBuffer) donnees = new Uint8Array(donnees);
    else if (!(donnees instanceof Uint8Array)) donnees = new Uint8Array(donnees);

    // Deux entrées de même nom rendraient l'archive ambiguë.
    let nom = entree.nom;
    if (nomsPris.has(nom)) {
      const point = nom.lastIndexOf('.');
      const base = point > 0 ? nom.slice(0, point) : nom;
      const ext = point > 0 ? nom.slice(point) : '';
      let n = 2;
      while (nomsPris.has(`${base} (${n})${ext}`)) n++;
      nom = `${base} (${n})${ext}`;
    }
    nomsPris.add(nom);

    preparees.push({ nomOctets: encodeur.encode(nom), donnees, crc: crc32(donnees) });
  }

  const poidsTotal = preparees.reduce((s, e) => s + e.donnees.length, 0);
  if (poidsTotal > LIMITE) {
    throw new Error('Archive de plus de 4 Go : au-delà, il faudrait le format ZIP64.');
  }

  const morceaux = [];
  const central = [];
  let position = 0;

  for (const e of preparees) {
    const tete = new Uint8Array(30 + e.nomOctets.length);
    const v = new DataView(tete.buffer);
    v.setUint32(0, 0x04034b50, true);          // signature
    v.setUint16(4, 20, true);                  // version minimale
    v.setUint16(6, 0x0800, true);              // noms en UTF-8
    v.setUint16(8, 0, true);                   // méthode : stocké
    v.setUint16(10, heure, true);
    v.setUint16(12, jour, true);
    v.setUint32(14, e.crc, true);
    v.setUint32(18, e.donnees.length, true);   // taille compressée
    v.setUint32(22, e.donnees.length, true);   // taille réelle
    v.setUint16(26, e.nomOctets.length, true);
    v.setUint16(28, 0, true);                  // pas de champ « extra »
    tete.set(e.nomOctets, 30);

    morceaux.push(tete, e.donnees);

    const fiche = new Uint8Array(46 + e.nomOctets.length);
    const c = new DataView(fiche.buffer);
    c.setUint32(0, 0x02014b50, true);
    c.setUint16(4, 20, true);                  // version d'écriture
    c.setUint16(6, 20, true);                  // version minimale
    c.setUint16(8, 0x0800, true);
    c.setUint16(10, 0, true);
    c.setUint16(12, heure, true);
    c.setUint16(14, jour, true);
    c.setUint32(16, e.crc, true);
    c.setUint32(20, e.donnees.length, true);
    c.setUint32(24, e.donnees.length, true);
    c.setUint16(28, e.nomOctets.length, true);
    c.setUint16(30, 0, true);                  // extra
    c.setUint16(32, 0, true);                  // commentaire
    c.setUint16(34, 0, true);                  // disque de départ
    c.setUint16(36, 0, true);                  // attributs internes
    c.setUint32(38, 0, true);                  // attributs externes
    c.setUint32(42, position, true);           // position de l'en-tête local
    fiche.set(e.nomOctets, 46);
    central.push(fiche);

    position += tete.length + e.donnees.length;
  }

  const debutCentral = position;
  let tailleCentral = 0;
  for (const fiche of central) {
    morceaux.push(fiche);
    tailleCentral += fiche.length;
  }

  const fin = new Uint8Array(22);
  const f = new DataView(fin.buffer);
  f.setUint32(0, 0x06054b50, true);
  f.setUint16(4, 0, true);                     // numéro de disque
  f.setUint16(6, 0, true);                     // disque du répertoire
  f.setUint16(8, preparees.length, true);
  f.setUint16(10, preparees.length, true);
  f.setUint32(12, tailleCentral, true);
  f.setUint32(16, debutCentral, true);
  f.setUint16(20, 0, true);                    // commentaire d'archive
  morceaux.push(fin);

  return new Blob(morceaux, { type: 'application/zip' });
}
