# vendor/

Fichiers tiers copiés tels quels, **non modifiés**.

| Fichier | Provenance | Version | Licence |
|---|---|---|---|
| `ffmpeg.js` | [`@ffmpeg/ffmpeg`](https://www.npmjs.com/package/@ffmpeg/ffmpeg) — `dist/umd/ffmpeg.js` | 0.12.10 | MIT |
| `814.ffmpeg.js` | `@ffmpeg/ffmpeg` — `dist/umd/814.ffmpeg.js` | 0.12.10 | MIT |
| `ffmpeg-util.js` | [`@ffmpeg/util`](https://www.npmjs.com/package/@ffmpeg/util) — `dist/umd/index.js` | 0.12.1 | MIT |

## Pourquoi ils sont ici plutôt que sur un CDN

La classe `FFmpeg` démarre un *worker*. Un navigateur refuse de créer un worker
à partir d'un script servi par un autre domaine — le chargement restait donc
bloqué indéfiniment quand ces fichiers venaient d'unpkg.

Servis depuis notre propre origine, le worker et son morceau de code
(`814.ffmpeg.js`, que `ffmpeg.js` va chercher tout seul à côté de lui) se
créent normalement.

Le gros moteur `ffmpeg-core.wasm` (~32 Mo) reste, lui, sur le CDN : il est
récupéré par `fetch` en mode CORS, ce qui est parfaitement autorisé entre
origines. Ça évite de charger 32 Mo dans le dépôt Git.

## Mettre à jour

```bash
V=0.12.10
curl -sL -o ffmpeg.js      "https://unpkg.com/@ffmpeg/ffmpeg@$V/dist/umd/ffmpeg.js"
curl -sL -o 814.ffmpeg.js  "https://unpkg.com/@ffmpeg/ffmpeg@$V/dist/umd/814.ffmpeg.js"
curl -sL -o ffmpeg-util.js "https://unpkg.com/@ffmpeg/util@0.12.1/dist/umd/index.js"
```

Le nom du second fichier (`814.ffmpeg.js`) est un identifiant de découpage
généré par webpack : **il change d'une version à l'autre**. Après une mise à
jour, vérifiez la liste réelle des fichiers :

```bash
curl -sL "https://unpkg.com/@ffmpeg/ffmpeg@$V/dist/umd/?meta"
```
