import { fromUrl } from 'geotiff';

// Load a sat3d stack (manifest + COGs) at a given max mesh dimension.
// geotiff.js reads the overview / does nearest resampling on the client.
export async function listStacks() {
  return (await fetch('/api/stacks')).json();
}

export async function loadStack(name, maxDim = 512, onProgress = () => {}) {
  const base = `/data/${name}`;
  const manifest = await (await fetch(`${base}/manifest.json`)).json();
  const [fullH, fullW] = manifest.shape;
  const step = Math.max(1, Math.ceil(Math.max(fullW, fullH) / maxDim));
  const w = Math.ceil(fullW / step), h = Math.ceil(fullH / step);

  const names = Object.keys(manifest.layers);
  const loaded = {};
  let done = 0;
  await Promise.all(names.map(async (n) => {
    const tiff = await fromUrl(`${base}/${manifest.layers[n]}`, { allowFullFile: true });
    const [band] = await tiff.readRasters({ width: w, height: h, resampleMethod: 'nearest' });
    loaded[n] = n === 'CLOUD_MASK' ? Float32Array.from(band, (v) => (v === 255 ? NaN : v)) : new Float32Array(band);
    onProgress(++done / names.length);
  }));
  const order = ['LST', 'LST_UNCERTAINTY', 'LWIR1_EMIS', 'NDVI'];
  const sorted = [...order.filter((n) => n in loaded), ...names.filter((n) => !order.includes(n)).sort()];
  const layers = Object.fromEntries(sorted.map((n) => [n, loaded[n]]));

  return { name, manifest, w, h, res: manifest.resolution_m * step, layers, stats: Object.fromEntries(sorted.map((n) => [n, stats(layers[n])])) };
}

export function stats(a) {
  const v = a.filter(Number.isFinite).sort();
  if (!v.length) return { n: 0 };
  const q = (p) => v[Math.min(v.length - 1, Math.floor(p * (v.length - 1)))];
  let s = 0, s2 = 0;
  for (const x of v) { s += x; s2 += x * x; }
  const mean = s / v.length;
  return { n: v.length, min: v[0], max: v[v.length - 1], mean, std: Math.sqrt(Math.max(0, s2 / v.length - mean * mean)), p2: q(0.02), p50: q(0.5), p98: q(0.98) };
}

// 2–98 % stretched true colour from the three visible SR bands.
export function trueColor(stack) {
  const { RED_SR: r, GREEN_SR: g, BLUE_SR: b } = stack.layers;
  const out = new Float32Array(stack.w * stack.h * 3);
  [r, g, b].forEach((band, k) => {
    const { p2, p98 } = stats(band);
    for (let i = 0; i < band.length; i++) out[i * 3 + k] = Math.pow(Math.min(1, Math.max(0, (band[i] - p2) / (p98 - p2))), 0.8);
  });
  return out;
}

// Band math: an expression over layer names, e.g. "(NIR_SR-RED_SR)/(NIR_SR+RED_SR)"
// or "LST - 273.15". Evaluated per pixel; runs locally on your own data.
export function evaluate(stack, expr) {
  const names = Object.keys(stack.layers).filter((n) => new RegExp(`\\b${n}\\b`).test(expr));
  const fn = new Function(...names, 'Math', `return (${expr});`);
  const arrs = names.map((n) => stack.layers[n]);
  const out = new Float32Array(stack.w * stack.h);
  const args = new Array(names.length);
  for (let i = 0; i < out.length; i++) {
    for (let k = 0; k < arrs.length; k++) args[k] = arrs[k][i];
    out[i] = fn(...args, Math);
  }
  return out;
}
