/* =========================================================================
   L'ATELIER — moteur audio/vidéo partagé (ffmpeg.wasm).

   Tout tourne dans l'onglet : aucun fichier n'est envoyé sur un serveur.
   Le moteur pèse ~32 Mo, il n'est téléchargé qu'au premier usage puis mis
   en cache par le navigateur.
   ========================================================================= */

const VERSION_CORE = '0.12.6';

/* Les miroirs ne servent qu'au gros moteur (~32 Mo), récupéré par `fetch`
   en mode CORS — ce qui est autorisé d'une origine à l'autre. */
const MIROIRS = [
  'https://unpkg.com',
  'https://cdn.jsdelivr.net/npm',
];

/* La classe FFmpeg, elle, doit être servie depuis NOTRE origine : elle lance
   un worker, et un navigateur refuse de créer un worker depuis un autre
   domaine. Ces deux fichiers font 7 Ko à eux deux et vivent dans vendor/.
   `import.meta.url` les localise correctement quel que soit l'outil appelant
   (racine, outils/sillon/, outils/gomme/…). */
const VENDOR = new URL('./vendor/', import.meta.url).href;

/* Le moteur multi-cœurs est 2 à 4 fois plus rapide, mais il exige que la page
   soit « isolée » (en-têtes COOP/COEP), ce qu'un hébergement statique comme
   GitHub Pages ne permet pas de régler. On peut forcer cette isolation avec un
   service worker, mais elle casse au passage le chargement des polices Google
   et des bibliothèques depuis un CDN. L'atelier choisit donc la fiabilité :
   moteur mono-cœur partout, et bascule automatique en multi-cœurs si vous
   hébergez un jour l'atelier derrière un serveur qui envoie ces en-têtes. */
export const multiCoeurs = () => typeof crossOriginIsolated !== 'undefined' && crossOriginIsolated === true;

let instance = null;
let chargement = null;
const auditeurs = { journal: new Set(), progression: new Set() };

/* ---------- Chargement des scripts UMD ---------- */

function injecter(url) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = url;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('Script inaccessible : ' + url));
    document.head.appendChild(s);
  });
}

async function injecterLocal(fichier, sonde) {
  if (sonde()) return;
  await injecter(VENDOR + fichier);
  if (!sonde()) {
    throw new Error(`vendor/${fichier} est chargé mais ne définit rien. ` +
                    `Le fichier est-il complet ?`);
  }
}

/* ---------- Chargement du moteur ---------- */

/**
 * Prépare ffmpeg.wasm. Idempotent : les appels suivants sont instantanés.
 * @param {(etape:string, part:number)=>void} [surEtape]
 */
export function charger(surEtape) {
  if (instance) return Promise.resolve(instance);
  if (chargement) return chargement;

  const dire = (etape, part) => surEtape?.(etape, part);

  chargement = (async () => {
    dire('Téléchargement du moteur…', 0.05);

    await injecterLocal('ffmpeg.js', () => !!window.FFmpegWASM?.FFmpeg);
    await injecterLocal('ffmpeg-util.js', () => !!window.FFmpegUtil?.toBlobURL);

    const { FFmpeg } = window.FFmpegWASM;
    const { toBlobURL } = window.FFmpegUtil;

    const paquet = multiCoeurs() ? 'core-mt' : 'core';
    const chemin = `/@ffmpeg/${paquet}@${VERSION_CORE}/dist/umd`;

    dire('Décompression du moteur…', 0.35);

    const ff = new FFmpeg();

    ff.on('log', ({ message }) => {
      auditeurs.journal.forEach((fn) => { try { fn(message); } catch (_) {} });
    });
    ff.on('progress', ({ progress }) => {
      auditeurs.progression.forEach((fn) => { try { fn(progress); } catch (_) {} });
    });

    /* Un miroir peut être injoignable : on essaie le suivant plutôt que
       d'échouer. Les trois fichiers viennent forcément du même miroir. */
    let config = null;
    let derniere = null;
    for (const miroir of MIROIRS) {
      const base = miroir + chemin;
      try {
        const essai = {
          coreURL: await toBlobURL(`${base}/ffmpeg-core.js`, 'text/javascript'),
          wasmURL: await toBlobURL(`${base}/ffmpeg-core.wasm`, 'application/wasm'),
        };
        if (paquet === 'core-mt') {
          essai.workerURL = await toBlobURL(`${base}/ffmpeg-core.worker.js`, 'text/javascript');
        }
        config = essai;
        break;
      } catch (e) { derniere = e; }
    }
    if (!config) {
      throw new Error('Aucun miroir n’a répondu. Vérifiez votre connexion. ' +
                      (derniere?.message || ''));
    }

    dire('Démarrage du moteur…', 0.8);
    await ff.load(config);

    dire('Moteur prêt', 1);
    instance = ff;
    return ff;
  })();

  chargement.catch(() => { chargement = null; });
  return chargement;
}

export const estPret = () => !!instance;

/* ---------- Exécution ---------- */

const TEMPS = /time=\s*(\d+):(\d+):(\d+(?:\.\d+)?)/;

/**
 * Lance une commande ffmpeg sur un ou plusieurs fichiers.
 *
 * @param {object} tache
 * @param {Array<{nom:string, donnees:File|Blob|Uint8Array}>} tache.entrees
 * @param {string[]} tache.args              arguments ffmpeg complets
 * @param {string|string[]} tache.sortie     nom(s) de fichier produit(s)
 * @param {number} [tache.duree]             durée attendue, pour la progression
 * @param {(part:number)=>void} [tache.surProgression]  0 → 1
 * @param {(ligne:string)=>void} [tache.surJournal]
 * @returns {Promise<Uint8Array|Uint8Array[]>}
 */
export async function executer(tache) {
  const {
    entrees = [], args, sortie,
    duree = 0, surProgression, surJournal,
  } = tache;

  const ff = await charger();
  const sorties = Array.isArray(sortie) ? sortie : [sortie];

  let dernierePart = 0;
  const avancer = (p) => {
    if (!surProgression) return;
    const borne = Math.min(0.999, Math.max(0, p));
    if (borne < dernierePart) return;      // la progression ne recule jamais
    dernierePart = borne;
    surProgression(borne);
  };

  const surLigne = (ligne) => {
    surJournal?.(ligne);
    if (!duree) return;
    const m = TEMPS.exec(ligne);
    if (m) avancer((+m[1] * 3600 + +m[2] * 60 + +m[3]) / duree);
  };
  const surPart = (p) => { if (!duree) avancer(p); };

  auditeurs.journal.add(surLigne);
  auditeurs.progression.add(surPart);

  const aEcrire = [];
  try {
    for (const e of entrees) {
      const donnees = e.donnees instanceof Uint8Array
        ? e.donnees
        : new Uint8Array(await e.donnees.arrayBuffer());
      await ff.writeFile(e.nom, donnees);
      aEcrire.push(e.nom);
    }

    const code = await ff.exec(args);
    if (code !== 0 && code !== undefined) {
      throw new Error(`ffmpeg a renvoyé le code ${code}`);
    }

    const produits = [];
    for (const nom of sorties) {
      let donnees;
      try {
        donnees = await ff.readFile(nom);
      } catch (_) {
        throw new Error(
          `ffmpeg n'a rien produit. Le format d'entrée est peut-être ` +
          `illisible, ou les réglages sont incompatibles — voir le journal.`,
        );
      }
      if (!donnees || !donnees.length) {
        throw new Error('Le fichier produit est vide — voir le journal technique.');
      }
      produits.push(donnees);
      aEcrire.push(nom);
    }

    surProgression?.(1);
    return Array.isArray(sortie) ? produits : produits[0];
  } finally {
    auditeurs.journal.delete(surLigne);
    auditeurs.progression.delete(surPart);
    for (const nom of aEcrire) {
      try { await ff.deleteFile(nom); } catch (_) {}
    }
  }
}

/* ---------- Analyse d'un fichier ---------- */

const RE_DUREE  = /Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)/;
const RE_AUDIO  = /Stream #\d+:\d+.*?:\s*Audio:\s*([a-z0-9_]+)/i;
const RE_VIDEO  = /Stream #\d+:\d+.*?:\s*Video:\s*([a-z0-9_]+)/i;
const RE_TAILLE = /Video:.*?,\s*(\d{2,5})x(\d{2,5})/i;
const RE_DEBIT  = /Audio:.*?,\s*(\d+)\s*kb\/s/i;

/**
 * Interroge ffmpeg sur un fichier sans rien produire.
 * `ffmpeg -i` sort toujours en erreur faute de sortie : on l'ignore.
 * @returns {Promise<{texte:string,codecAudio:string,codecVideo:string,duree:number,largeur:number,hauteur:number,debitAudio:number}>}
 */
export async function analyser(fichier) {
  const ff = await charger();
  const nom = 'sonde.' + (ext(fichier.name) || 'bin');
  const lignes = [];
  const capter = (l) => lignes.push(l);

  auditeurs.journal.add(capter);
  try {
    await ff.writeFile(nom, new Uint8Array(await fichier.arrayBuffer()));
    try { await ff.exec(['-hide_banner', '-i', nom]); } catch (_) { /* attendu */ }
  } finally {
    auditeurs.journal.delete(capter);
    try { await ff.deleteFile(nom); } catch (_) {}
  }

  const texte = lignes.join('\n');
  const d = RE_DUREE.exec(texte);
  const t = RE_TAILLE.exec(texte);

  return {
    texte,
    codecAudio: RE_AUDIO.exec(texte)?.[1]?.toLowerCase() || '',
    codecVideo: RE_VIDEO.exec(texte)?.[1]?.toLowerCase() || '',
    duree: d ? +d[1] * 3600 + +d[2] * 60 + +d[3] : 0,
    largeur: t ? +t[1] : 0,
    hauteur: t ? +t[2] : 0,
    debitAudio: +(RE_DEBIT.exec(texte)?.[1] || 0),
  };
}

/* Codecs vidéo que le moteur wasm ne sait pas décoder. La liste est volontai-
   rement courte : on n'y met que ce qui a été constaté, pas ce qu'on suppose.
   AV1 arrive de plus en plus (téléchargements YouTube, enregistreurs d'écran
   récents), et l'erreur brute de ffmpeg — « code 1 » — n'aide personne. */
const SANS_DECODEUR = {
  av1: 'AV1',
  libaom_av1: 'AV1',
  av01: 'AV1',
};

/**
 * Renvoie un message d'explication si la vidéo ne peut pas être décodée ici,
 * sinon `null`. À n'appeler que lorsqu'on va réellement réencoder l'image :
 * une simple copie de flux (`-c copy`) ou une extraction audio (`-vn`) ne
 * décode rien et fonctionne quel que soit le codec.
 */
export function obstacleVideo(infos) {
  const nom = SANS_DECODEUR[infos?.codecVideo];
  if (!nom) return null;
  return `Cette vidéo est encodée en ${nom}, un format que le moteur du ` +
         `navigateur ne sait pas décoder. Convertissez-la d'abord avec un ` +
         `ffmpeg installé sur la machine, ou choisissez « changer le ` +
         `conteneur seulement », qui recopie les pistes sans les décoder.`;
}

/** Conteneur naturel pour une piste audio recopiée telle quelle. */
export function contenantPour(codec) {
  switch (codec) {
    case 'aac':                 return 'm4a';
    case 'mp3':                 return 'mp3';
    case 'opus':                return 'opus';
    case 'vorbis':              return 'ogg';
    case 'flac':                return 'flac';
    case 'alac':                return 'm4a';
    case 'pcm_s16le':
    case 'pcm_s24le':
    case 'pcm_f32le':           return 'wav';
    case 'ac3':                 return 'ac3';
    default:                    return '';   // pas de recopie possible
  }
}

/** Interrompt la commande en cours. Le moteur reste utilisable ensuite. */
export async function interrompre() {
  if (!instance) return;
  try { await instance.terminate(); } catch (_) {}
  instance = null;
  chargement = null;
}

/* ---------- Utilitaires ---------- */

/** Extension d'un nom, sans le point, en minuscules. */
export const ext = (nom = '') => (nom.match(/\.([^./\\]+)$/)?.[1] || '').toLowerCase();

/** Un nom d'entrée sûr pour le système de fichiers virtuel de ffmpeg. */
export function nomEntree(fichier, index = 0) {
  const e = ext(fichier.name) || 'bin';
  return `e${index}.${e}`;
}

/** Types MIME des formats produits par l'atelier. */
export const MIME = {
  mp3: 'audio/mpeg',   m4a: 'audio/mp4',  aac: 'audio/aac',
  wav: 'audio/wav',    ogg: 'audio/ogg',  opus: 'audio/ogg',
  flac: 'audio/flac',
  mp4: 'video/mp4',    webm: 'video/webm', mkv: 'video/x-matroska',
  mov: 'video/quicktime', gif: 'image/gif',
  jpg: 'image/jpeg',   jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp',
};

export const mimeDe = (extension) => MIME[String(extension).toLowerCase()] || 'application/octet-stream';

/** Assemble un Blob téléchargeable à partir de la sortie de `executer`. */
export function versBlob(donnees, extension) {
  const octets = donnees instanceof Uint8Array ? donnees : new Uint8Array(donnees);
  // On recopie dans un ArrayBuffer neuf : la mémoire de ffmpeg est réutilisée.
  return new Blob([octets.slice()], { type: mimeDe(extension) });
}
