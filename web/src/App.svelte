<script>
  import { onMount } from 'svelte';
  import { TerrainView } from './lib/terrain.js';
  import { listStacks, loadStack, stats, trueColor, evaluate } from './lib/stack.js';
  import { RAMPS, sample, cssGradient, defaultRamp } from './lib/colormaps.js';
  import StackDiagram from './lib/StackDiagram.svelte';

  const TABS = { map: 'Map', stack: 'Tech stack' };
  let tab = $state(location.hash === '#stack' ? 'stack' : 'map');
  $effect(() => { history.replaceState(null, '', tab === 'map' ? location.pathname : '#stack'); });

  const PRESET_EXPRS = {
    'NDVI': '(NIR_SR - RED_SR) / (NIR_SR + RED_SR)',
    'NDRE (red-edge)': '(NIR_SR - REDEDGE1_SR) / (NIR_SR + REDEDGE1_SR)',
    'LST °C': 'LST - 273.15',
    'LST anomaly (K)': 'LST - __MEAN_LST__',
    'Cool & green (ET proxy)': '(NIR_SR - RED_SR) / (NIR_SR + RED_SR) > 0.5 && LST < 305 ? 1 : 0',
  };

  let canvas, wrap, view;
  let stacks = $state([]);
  let stackName = $state('');
  let maxDim = $state(512);
  let stack = $state.raw(null);
  let progress = $state(0);
  let loading = $state(false);
  let error = $state('');

  let layer = $state('LST');
  let exprText = $state(PRESET_EXPRS['NDVI']);
  let exprArr = $state.raw(null);
  let exprError = $state('');
  let ramp = $state('inferno');
  let lo = $state(0), hi = $state(1);
  let ex = $state(3);
  let sunAz = $state(225), sunAlt = $state(45);
  let maskClouds = $state(true);
  let thOn = $state(false), thOp = $state('>'), thVal = $state(0);
  let probe = $state(null);

  let tc = $state.raw(null);
  const layerNames = $derived(stack ? Object.keys(stack.layers) : []);

  const active = $derived.by(() => {
    if (!stack || layer === 'TRUE_COLOR') return null;
    if (layer === 'EXPRESSION') return exprArr;
    return stack.layers[layer] ?? null;
  });
  const activeStats = $derived(active ? (layer === 'EXPRESSION' ? stats(active) : stack.stats[layer]) : null);

  // Histogram (64 bins between lo..hi)
  const hist = $derived.by(() => {
    if (!active || !(hi > lo)) return null;
    const bins = new Array(64).fill(0);
    for (const v of active) if (Number.isFinite(v) && v >= lo && v <= hi) bins[Math.min(63, Math.floor(((v - lo) / (hi - lo)) * 64))]++;
    return { bins, max: Math.max(...bins) };
  });

  // Threshold analysis: count, share, area, and conditions inside the mask
  const thResult = $derived.by(() => {
    if (!thOn || !active || !stack) return null;
    const pass = thOp === '>' ? (v) => v > thVal : (v) => v < thVal;
    const cloud = stack.layers.CLOUD_MASK;
    let n = 0, valid = 0, lst = 0, ndvi = 0, dem = 0;
    const { LST, RED_SR, NIR_SR, DEM } = stack.layers;
    for (let i = 0; i < active.length; i++) {
      const v = active[i];
      if (!Number.isFinite(v) || (maskClouds && cloud?.[i] === 1)) continue;
      valid++;
      if (pass(v)) {
        n++; lst += LST?.[i] ?? 0; dem += DEM?.[i] ?? 0;
        ndvi += NIR_SR && RED_SR ? (NIR_SR[i] - RED_SR[i]) / (NIR_SR[i] + RED_SR[i]) : 0;
      }
    }
    return { n, pct: (100 * n) / valid, km2: (n * stack.res * stack.res) / 1e6, lst: lst / n, ndvi: ndvi / n, dem: dem / n };
  });

  function resetRange() {
    if (activeStats?.n) { lo = +activeStats.p2.toPrecision(4); hi = +activeStats.p98.toPrecision(4); thVal = +(lo + (hi - lo) * 0.8).toPrecision(4); }
  }

  function selectLayer(name) {
    layer = name;
    if (name !== 'TRUE_COLOR') ramp = name === 'EXPRESSION' ? 'rdbu' : defaultRamp(name);
    queueMicrotask(resetRange);
  }

  function runExpr() {
    try {
      const resolved = exprText.replaceAll('__MEAN_LST__', String(stack.stats.LST.mean));
      exprArr = evaluate(stack, resolved);
      exprError = '';
      selectLayer('EXPRESSION');
    } catch (e) { exprError = e.message; }
  }

  async function open(name) {
    loading = true; error = ''; progress = 0; probe = null;
    try {
      const s = await loadStack(name, maxDim, (p) => (progress = p));
      tc = trueColor(s);
      exprArr = null;
      view.setStack(s);
      view.setExaggeration(ex);
      stack = s;
      selectLayer(s.layers[layer] ? layer : 'LST');
    } catch (e) { error = String(e); }
    loading = false;
  }

  // Repaint whenever the drape inputs change
  $effect(() => {
    if (!stack || !view) return;
    const N = stack.w * stack.h, rgb = new Float32Array(N * 3);
    const cloud = stack.layers.CLOUD_MASK;
    if (layer === 'TRUE_COLOR' || !active) {
      rgb.set(tc);
    } else {
      const r = RAMPS[ramp], span = hi - lo || 1;
      const pass = thOp === '>' ? (v) => v > thVal : (v) => v < thVal;
      for (let i = 0; i < N; i++) {
        const v = active[i];
        let c;
        if (!Number.isFinite(v)) c = [0.2, 0.2, 0.22];
        else {
          c = sample(r, (v - lo) / span);
          if (thOn) c = pass(v) ? [0, 0.9, 1] : [c[0] * 0.35, c[1] * 0.35, c[2] * 0.35];
        }
        rgb[i * 3] = c[0]; rgb[i * 3 + 1] = c[1]; rgb[i * 3 + 2] = c[2];
      }
    }
    if (maskClouds && cloud) for (let i = 0; i < N; i++) if (cloud[i] === 1) { rgb[i * 3] = rgb[i * 3 + 1] = rgb[i * 3 + 2] = 0.92; }
    view.setColors(rgb);
  });
  $effect(() => { view && stack && view.setExaggeration(ex); });
  $effect(() => { view?.setSun(sunAz, sunAlt); });

  let down = null;
  function onPointerUp(e) {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
    const p = view.pick(e.clientX, e.clientY);
    if (!p) return;
    const vals = Object.fromEntries(layerNames.map((n) => [n, stack.layers[n][p.i]]));
    if (exprArr) vals.EXPRESSION = exprArr[p.i];
    probe = { ...p, vals };
  }

  function saveImage() {
    const a = document.createElement('a');
    a.href = view.screenshot();
    a.download = `${stack.name}-${layer}.png`;
    a.click();
  }

  const fmt = (v) => (v == null || !Number.isFinite(v) ? '—' : Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(3));

  onMount(() => {
    view = new TerrainView(canvas);
    const ro = new ResizeObserver(() => view.resize(wrap.clientWidth, wrap.clientHeight));
    ro.observe(wrap);
    listStacks().then((s) => {
      stacks = s;
      if (s.length) { stackName = s[0]; open(s[0]); }
      else error = 'No stacks found in ../data. Build one: uv run sat3d-build --preset salinas --out data/salinas';
    });
    return () => { ro.disconnect(); view.dispose(); };
  });
</script>

<div class="app">
<nav class="tabs" role="tablist">
  {#each Object.entries(TABS) as [k, label]}
    <button role="tab" aria-selected={tab === k} class:on={tab === k} onclick={() => (tab = k)}>{label}</button>
  {/each}
</nav>

<!-- Map stays mounted (hidden) so the WebGL scene and analysis state survive tab switches -->
<div class="layout" hidden={tab !== 'map'}>
  <aside>
    <header>
      <h1>sat3d · DEM drape</h1>
      {#if stack}
        <div class="muted">
          Landsat {stack.manifest.sources.landsat.datetime.slice(0, 10)} · S2 {stack.manifest.sources.sentinel2.datetime.slice(0, 10)}<br />
          {stack.manifest.crs} · {stack.res} m mesh · {stack.w}×{stack.h}
        </div>
      {/if}
    </header>

    <section>
      <div class="row">
        <select bind:value={stackName} onchange={() => open(stackName)} disabled={loading}>
          {#each stacks as s}<option value={s}>{s}</option>{/each}
        </select>
        <select bind:value={maxDim} onchange={() => open(stackName)} disabled={loading} title="Mesh resolution">
          <option value={256}>coarse</option><option value={512}>medium</option><option value={1024}>full</option>
        </select>
      </div>
      {#if loading}<progress value={progress}></progress>{/if}
      {#if error}<p class="err">{error}</p>{/if}
    </section>

    {#if stack}
      <section>
        <h2>Drape</h2>
        <select value={layer} onchange={(e) => selectLayer(e.currentTarget.value)}>
          <option value="TRUE_COLOR">True colour (S2)</option>
          {#each layerNames as n}<option value={n}>{n}</option>{/each}
          {#if exprArr}<option value="EXPRESSION">Expression result</option>{/if}
        </select>
        {#if layer !== 'TRUE_COLOR'}
          <div class="row">
            <select bind:value={ramp}>{#each Object.keys(RAMPS) as r}<option>{r}</option>{/each}</select>
            <button onclick={resetRange} title="Stretch 2–98 %">auto</button>
          </div>
          <div class="legend" style:background={cssGradient(RAMPS[ramp])}></div>
          <div class="row range">
            <input type="number" step="any" bind:value={lo} /><input type="number" step="any" bind:value={hi} />
          </div>
          {#if hist}
            <svg class="hist" viewBox="0 0 64 20" preserveAspectRatio="none">
              {#each hist.bins as b, i}<rect x={i} y={20 - (20 * b) / hist.max} width="0.9" height={(20 * b) / hist.max} />{/each}
              {#if thOn && thVal >= lo && thVal <= hi}<line x1={(64 * (thVal - lo)) / (hi - lo)} x2={(64 * (thVal - lo)) / (hi - lo)} y1="0" y2="20" />{/if}
            </svg>
          {/if}
          {#if activeStats?.n}
            <div class="muted mono">mean {fmt(activeStats.mean)} · sd {fmt(activeStats.std)} · median {fmt(activeStats.p50)}</div>
          {/if}
        {/if}
        <label class="chk"><input type="checkbox" bind:checked={maskClouds} /> Mask clouds</label>
      </section>

      <section>
        <h2>Terrain</h2>
        <label>Exaggeration {ex}×<input type="range" min="1" max="10" step="0.5" bind:value={ex} /></label>
        <label>Sun azimuth {sunAz}°<input type="range" min="0" max="360" step="5" bind:value={sunAz} /></label>
        <label>Sun altitude {sunAlt}°<input type="range" min="5" max="90" step="5" bind:value={sunAlt} /></label>
      </section>

      <section>
        <h2>Band math</h2>
        <select onchange={(e) => { exprText = PRESET_EXPRS[e.currentTarget.value]; runExpr(); }}>
          <option disabled selected>presets…</option>
          {#each Object.keys(PRESET_EXPRS) as k}<option>{k}</option>{/each}
        </select>
        <textarea rows="2" bind:value={exprText} spellcheck="false"></textarea>
        <button onclick={runExpr}>Run</button>
        {#if exprError}<p class="err">{exprError}</p>{/if}
        <div class="muted">Layers: {layerNames.join(', ')}</div>
      </section>

      {#if layer !== 'TRUE_COLOR'}
        <section>
          <h2>Threshold analysis</h2>
          <div class="row">
            <label class="chk"><input type="checkbox" bind:checked={thOn} /> {layer}</label>
            <select bind:value={thOp}><option>&gt;</option><option>&lt;</option></select>
            <input type="number" step="any" bind:value={thVal} />
          </div>
          {#if thResult}
            <div class="mono">
              {thResult.n.toLocaleString()} px · {thResult.pct.toFixed(1)}% · {thResult.km2.toFixed(2)} km²<br />
              inside: LST {fmt(thResult.lst)} K · NDVI {fmt(thResult.ndvi)} · elev {fmt(thResult.dem)} m
            </div>
          {/if}
        </section>
      {/if}

      <section>
        <h2>Probe</h2>
        {#if probe}
          <table class="mono">
            <tbody>
              <tr><td>row, col</td><td>{probe.row}, {probe.col}</td></tr>
              {#each Object.entries(probe.vals) as [k, v]}<tr class:hl={k === layer}><td>{k}</td><td>{fmt(v)}</td></tr>{/each}
            </tbody>
          </table>
        {:else}<div class="muted">Click the terrain to read every layer at that point.</div>{/if}
      </section>

      <section><button onclick={saveImage}>Save PNG</button></section>
    {/if}
  </aside>

  <main bind:this={wrap} onpointerdown={(e) => (down = [e.clientX, e.clientY])} onpointerup={onPointerUp}>
    <canvas bind:this={canvas}></canvas>
  </main>
</div>

{#if tab === 'stack'}<div class="page"><StackDiagram /></div>{/if}
</div>

<style>
  .app { display: flex; flex-direction: column; height: 100%; }
  .tabs { display: flex; gap: 2px; padding: 6px 10px 0; background: var(--bg); border-bottom: 1px solid var(--border); flex: none; }
  .tabs button { width: auto; border: 1px solid transparent; border-bottom: none; border-radius: 6px 6px 0 0;
    background: none; color: var(--muted); padding: 7px 16px; margin-bottom: -1px; }
  .tabs button:hover { color: var(--fg); border-color: transparent; }
  .tabs button.on { background: var(--panel); color: var(--fg); border-color: var(--border); }
  .layout { display: flex; flex: 1; min-height: 0; }
  .layout[hidden] { display: none; }
  .page { flex: 1; min-height: 0; }
  aside { width: 300px; flex: none; overflow-y: auto; background: var(--panel); border-right: 1px solid var(--border); padding: 12px 14px; }
  main { flex: 1; position: relative; min-width: 0; }
  canvas { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
  h1 { font-size: 15px; margin: 0 0 4px; }
  h2 { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 0 0 6px; }
  section { padding: 10px 0; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 6px; }
  header { padding-bottom: 8px; }
  .row { display: flex; gap: 6px; align-items: center; }
  .row > * { flex: 1; min-width: 0; }
  .range input { width: 100%; }
  label { display: flex; flex-direction: column; gap: 2px; }
  label.chk { flex-direction: row; align-items: center; gap: 6px; }
  select, textarea, button { width: 100%; }
  textarea { font-family: ui-monospace, monospace; font-size: 12px; resize: vertical; }
  .legend { height: 10px; border-radius: 3px; }
  .hist { width: 100%; height: 40px; }
  .hist rect { fill: var(--muted); }
  .hist line { stroke: var(--hit); stroke-width: 0.4; }
  .muted { color: var(--muted); font-size: 11px; }
  .mono { font-family: ui-monospace, monospace; font-size: 11px; }
  .err { color: #ff7b72; margin: 0; font-size: 12px; }
  table { border-collapse: collapse; width: 100%; }
  td { padding: 1px 0; } td:last-child { text-align: right; }
  tr.hl td { color: var(--accent); }
  progress { width: 100%; }
  @media (max-width: 700px) {
    .layout { flex-direction: column-reverse; }
    aside { width: 100%; height: 45%; border-right: none; border-top: 1px solid var(--border); }
  }
</style>
