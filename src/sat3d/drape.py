"""Export an analog stack as a self-contained interactive 3D HTML viewer.

The DEM becomes a three.js mesh; any layer (LST, NDVI, true colour, ...) is
draped as vertex colours. Click a point to read every layer's value there;
the threshold control is a tiny in-browser analysis (e.g. LST > 315 K).
This is the "small scale" prototype: everything ships in one HTML file.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
import rasterio

DEFAULT_LAYERS = ["LST", "NDVI", "LST_UNCERTAINTY", "LWIR1_EMIS", "REDEDGE1_SR", "NIR_SR", "DEM"]


def _b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def export_html(stack_dir: str | Path, out_html: str | Path | None = None, max_dim: int = 400,
                layers: list[str] | None = None) -> Path:
    stack = Path(stack_dir)
    manifest = json.loads((stack / "manifest.json").read_text())
    dem_full = rasterio.open(stack / "DEM.tif").read(1)
    step = max(1, int(np.ceil(max(dem_full.shape) / max_dim)))

    def load(name):
        return rasterio.open(stack / f"{name}.tif").read(1)[::step, ::step].astype("float32")

    dem = load("DEM")
    h, w = dem.shape
    payload = {}
    for name in layers or DEFAULT_LAYERS:
        if (stack / f"{name}.tif").exists():
            a = load(name)
            v = a[np.isfinite(a)]
            payload[name] = {"data": _b64(a), "p2": float(np.percentile(v, 2)), "p98": float(np.percentile(v, 98))}

    # True colour as 8-bit RGB with a per-band 2-98% stretch and a little gamma
    rgb = []
    for b in ("RED_SR", "GREEN_SR", "BLUE_SR"):
        a = load(b)
        lo, hi = np.nanpercentile(a, [2, 98])
        rgb.append((np.clip((a - lo) / (hi - lo), 0, 1) ** 0.8 * 255).astype("uint8"))
    truecolor = _b64(np.stack(rgb, -1))

    meta = {"w": w, "h": h, "res": manifest["resolution_m"] * step, "name": manifest["name"],
            "sources": manifest["sources"], "dem": _b64(np.nan_to_num(dem, nan=0.0)),
            "layers": payload, "truecolor": truecolor}
    html = TEMPLATE.replace("__DATA__", json.dumps(meta))
    out = Path(out_html) if out_html else stack / "viewer.html"
    out.write_text(html)
    return out


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>sat3d drape viewer</title>
<style>
:root{--bg:#0f1115;--panel:#1a1d24ee;--fg:#e6e6e6;--muted:#9aa3b2;--accent:#ffb454}
html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);font:13px/1.4 system-ui,sans-serif;overflow:hidden}
#ui{position:absolute;top:12px;left:12px;background:var(--panel);padding:12px 14px;border-radius:8px;width:260px;max-width:calc(100vw - 52px)}
#ui h1{font-size:14px;margin:0 0 6px} #ui .muted{color:var(--muted);font-size:11px}
label{display:block;margin-top:8px} select,input[type=range],input[type=number]{width:100%;box-sizing:border-box}
#probe{margin-top:10px;font-family:ui-monospace,monospace;font-size:11px;white-space:pre}
#legend{height:10px;border-radius:3px;margin-top:6px} #lg{display:flex;justify-content:space-between;font-size:11px;color:var(--muted)}
</style></head><body>
<div id="ui">
  <h1 id="title"></h1><div class="muted" id="src"></div>
  <label>Drape layer <select id="layer"></select></label>
  <div id="legend"></div><div id="lg"><span id="lo"></span><span id="hi"></span></div>
  <label>Vertical exaggeration <span id="exv"></span><input id="ex" type="range" min="1" max="10" step="0.5" value="3"></label>
  <label><input type="checkbox" id="thon"> Highlight where layer &gt; <input id="th" type="number" step="any"></label>
  <div class="muted" id="thstat"></div>
  <div id="probe">Click the terrain to probe values.</div>
</div>
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js","three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"}}</script>
<script type="module">
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
const D = __DATA__;
const dec = (b, T) => { const s = atob(b), u = new Uint8Array(s.length); for (let i=0;i<s.length;i++) u[i]=s.charCodeAt(i); return new T(u.buffer); };
const W=D.w, H=D.h, N=W*H, dem=dec(D.dem, Float32Array), tc=dec(D.truecolor, Uint8Array);
const L={}; for (const [k,v] of Object.entries(D.layers)) L[k]={...v, a:dec(v.data, Float32Array)};
document.getElementById('title').textContent=D.name;
document.getElementById('src').textContent=`Landsat ${D.sources.landsat.datetime.slice(0,10)} · S2 ${D.sources.sentinel2.datetime.slice(0,10)} · ${D.res} m mesh`;
const sel=document.getElementById('layer');
for (const k of ['TRUE_COLOR', ...Object.keys(L)]) sel.add(new Option(k,k));
sel.value = L.LST ? 'LST' : 'TRUE_COLOR';

// colour ramps (approx. inferno / viridis)
const RAMPS={inferno:[[0,0,4],[87,16,110],[188,55,84],[249,142,9],[252,255,164]],
             viridis:[[68,1,84],[59,82,139],[33,145,140],[94,201,98],[253,231,37]]};
const ramp=(r,t)=>{t=Math.min(1,Math.max(0,t));const n=r.length-1,i=Math.min(n-1,Math.floor(t*n)),f=t*n-i;return r[i].map((c,j)=>(c+(r[i+1][j]-c)*f)/255);};
const rampFor=k=>/NDVI|SR|EMIS/.test(k)?RAMPS.viridis:RAMPS.inferno;

const scene=new THREE.Scene(); scene.background=new THREE.Color(0x0f1115);
const cam=new THREE.PerspectiveCamera(45, innerWidth/innerHeight, 10, 1e7);
const ren=new THREE.WebGLRenderer({antialias:true}); ren.setPixelRatio(devicePixelRatio); ren.setSize(innerWidth,innerHeight);
document.body.appendChild(ren.domElement);
const geo=new THREE.PlaneGeometry((W-1)*D.res,(H-1)*D.res,W-1,H-1);
const col=new Float32Array(N*3); geo.setAttribute('color', new THREE.BufferAttribute(col,3));
const mesh=new THREE.Mesh(geo,new THREE.MeshLambertMaterial({vertexColors:true}));
mesh.rotation.x=-Math.PI/2; scene.add(mesh);
scene.add(new THREE.AmbientLight(0xffffff,0.55));
const sun=new THREE.DirectionalLight(0xffffff,1.6); sun.position.set(-1,1.2,0.6); scene.add(sun);
const ext=Math.max(W,H)*D.res; cam.position.set(0, ext*0.55, ext*0.75);
const ctl=new OrbitControls(cam, ren.domElement); ctl.enableDamping=true;

function setHeights(){ const ex=+document.getElementById('ex').value; document.getElementById('exv').textContent=ex+'×';
  const p=geo.attributes.position; for(let i=0;i<N;i++) p.setZ(i, dem[i]*ex); p.needsUpdate=true; geo.computeVertexNormals(); }
function paint(){ const k=sel.value, thon=document.getElementById('thon').checked, th=+document.getElementById('th').value;
  const lg=document.getElementById('legend'); let hits=0, valid=0;
  if(k==='TRUE_COLOR'){ for(let i=0;i<N;i++){col[i*3]=tc[i*3]/255;col[i*3+1]=tc[i*3+1]/255;col[i*3+2]=tc[i*3+2]/255;}
    lg.style.background='none'; document.getElementById('lo').textContent=''; document.getElementById('hi').textContent=''; }
  else { const l=L[k], r=rampFor(k), span=l.p98-l.p2;
    for(let i=0;i<N;i++){ const v=l.a[i]; if(!isFinite(v)){col.fill(0.2,i*3,i*3+3);continue;} valid++;
      let c=ramp(r,(v-l.p2)/span);
      if(thon){ if(v>th){hits++; c=[0,0.9,1];} else c=c.map(x=>x*0.35); }
      col.set(c,i*3); }
    lg.style.background=`linear-gradient(90deg,${r.map(c=>`rgb(${c})`).join(',')})`;
    document.getElementById('lo').textContent=l.p2.toFixed(3); document.getElementById('hi').textContent=l.p98.toFixed(3); }
  document.getElementById('thstat').textContent = thon && k!=='TRUE_COLOR' ?
    `${hits.toLocaleString()} px (${(100*hits/valid).toFixed(1)}%, ${(hits*D.res*D.res/1e6).toFixed(2)} km²) above threshold` : '';
  geo.attributes.color.needsUpdate=true; }
sel.onchange=()=>{ const l=L[sel.value]; if(l) document.getElementById('th').value=+(l.p2+(l.p98-l.p2)*0.8).toPrecision(4); paint(); };
document.getElementById('ex').oninput=setHeights;
document.getElementById('thon').onchange=paint; document.getElementById('th').oninput=paint;

const ray=new THREE.Raycaster(), m=new THREE.Vector2(); let down;
ren.domElement.addEventListener('pointerdown',e=>down=[e.clientX,e.clientY]);
ren.domElement.addEventListener('pointerup',e=>{ if(Math.hypot(e.clientX-down[0],e.clientY-down[1])>4) return;
  m.set(e.clientX/innerWidth*2-1, -e.clientY/innerHeight*2+1); ray.setFromCamera(m,cam);
  const hit=ray.intersectObject(mesh)[0]; if(!hit) return; const loc=mesh.worldToLocal(hit.point.clone());
  const c=Math.round(loc.x/D.res+(W-1)/2), r=Math.round((H-1)/2-loc.y/D.res), i=r*W+c;
  document.getElementById('probe').textContent=`row ${r}, col ${c}\n`+Object.entries(L).map(([k,l])=>`${k.padEnd(16)}${l.a[i].toFixed(4)}`).join('\n'); });
addEventListener('resize',()=>{cam.aspect=innerWidth/innerHeight;cam.updateProjectionMatrix();ren.setSize(innerWidth,innerHeight);});
setHeights(); sel.onchange();
(function loop(){requestAnimationFrame(loop);ctl.update();ren.render(scene,cam);})();
</script></body></html>
"""
