// Small perceptual ramps (approximations of matplotlib's), as 0..1 RGB stops.
const stops = {
  inferno: [[0, 0, 4], [87, 16, 110], [188, 55, 84], [249, 142, 9], [252, 255, 164]],
  viridis: [[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]],
  terrain: [[40, 90, 60], [120, 160, 90], [200, 190, 130], [150, 120, 90], [250, 250, 250]],
  rdbu: [[33, 102, 172], [146, 197, 222], [247, 247, 247], [244, 165, 130], [178, 24, 43]],
};
export const RAMPS = Object.fromEntries(Object.entries(stops).map(([k, v]) => [k, v.map((c) => c.map((x) => x / 255))]));

export function sample(ramp, t) {
  t = Math.min(1, Math.max(0, t));
  const n = ramp.length - 1, i = Math.min(n - 1, Math.floor(t * n)), f = t * n - i;
  const a = ramp[i], b = ramp[i + 1];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

export function cssGradient(ramp) {
  return `linear-gradient(90deg, ${ramp.map((c) => `rgb(${c.map((x) => Math.round(x * 255)).join(',')})`).join(',')})`;
}

export function defaultRamp(layer) {
  if (/NDVI|_SR|EMIS/.test(layer)) return 'viridis';
  if (layer === 'DEM') return 'terrain';
  return 'inferno';
}
