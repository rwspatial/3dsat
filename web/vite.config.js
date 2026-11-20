import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import fs from 'node:fs';
import path from 'node:path';

// Stacks built by `sat3d-build` live in ../data/<name>/ (manifest.json + *.tif).
// Serve them read-only at /data/* and list them at /api/stacks, without copying
// them into the bundle.
const DATA_DIR = path.resolve(import.meta.dirname, process.env.SAT3D_DATA ?? '../data');

function stackData() {
  const mw = (req, res, next) => {
    const url = decodeURIComponent((req.url ?? '').split('?')[0]);
    if (url === '/api/stacks') {
      const stacks = fs.existsSync(DATA_DIR)
        ? fs.readdirSync(DATA_DIR).filter((d) => fs.existsSync(path.join(DATA_DIR, d, 'manifest.json')))
        : [];
      res.setHeader('Content-Type', 'application/json');
      return res.end(JSON.stringify(stacks));
    }
    if (!url.startsWith('/data/')) return next();
    const file = path.resolve(DATA_DIR, '.' + url.slice(5));
    if (!file.startsWith(DATA_DIR + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      res.statusCode = 404;
      return res.end('not found');
    }
    const type = file.endsWith('.json') ? 'application/json' : file.endsWith('.tif') ? 'image/tiff' : 'application/octet-stream';
    const size = fs.statSync(file).size;
    res.setHeader('Content-Type', type);
    res.setHeader('Accept-Ranges', 'bytes');
    // COG readers (geotiff.js) fetch headers and tiles with HTTP Range requests
    const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range ?? '');
    if (m) {
      let start = m[1] === '' ? size - +m[2] : +m[1];
      let end = m[1] !== '' && m[2] !== '' ? Math.min(+m[2], size - 1) : size - 1;
      if (start >= size || start > end) {
        res.statusCode = 416;
        res.setHeader('Content-Range', `bytes */${size}`);
        return res.end();
      }
      res.statusCode = 206;
      res.setHeader('Content-Range', `bytes ${start}-${end}/${size}`);
      res.setHeader('Content-Length', end - start + 1);
      return fs.createReadStream(file, { start, end }).pipe(res);
    }
    res.setHeader('Content-Length', size);
    fs.createReadStream(file).pipe(res);
  };
  return {
    name: 'sat3d-stack-data',
    configureServer(s) { s.middlewares.use(mw); },
    configurePreviewServer(s) { s.middlewares.use(mw); },
  };
}

export default defineConfig({ plugins: [svelte(), stackData()] });
