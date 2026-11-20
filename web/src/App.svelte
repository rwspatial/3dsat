<script>
  import { onMount } from 'svelte';
  import { TerrainView } from './lib/terrain.js';
  import { listStacks, loadStack, stats, trueColor, evaluate } from './lib/stack.js';
  import { RAMPS, sample, cssGradient, defaultRamp } from './lib/colormaps.js';
  import StackDiagram from './lib/StackDiagram.svelte';

  const TABS = { map: 'Map', stack: 'Tech stack' };
  let tab = $state(location.hash === '#stack' ? 'stack' : 'map');
  $effect(() => { history.replaceState(null, '', tab === 'map' ? location.pathname : '#stack'); });

  // Named calculations. Selected as layer "calc:<name>"; "calc:Custom" uses whatever formula is typed.
  // (NDVI is not here because it already ships as a base raster.)
  const CALCS = {
    'NDRE': { expr: '(NIR_SR - REDEDGE1_SR) / (NIR_SR + REDEDGE1_SR)', ramp: 'viridis', note: 'Red-edge NDVI: crop chlorophyll / N status' },
    'CIre': { expr: 'NIR_SR / REDEDGE1_SR - 1', ramp: 'viridis', note: 'Red-edge chlorophyll index' },
    'NDWI': { expr: '(GREEN_SR - NIR_SR) / (GREEN_SR + NIR_SR)', ramp: 'rdbu', note: 'Open water > 0' },
    'LST °C': { expr: 'LST - 273.15', ramp: 'inferno', note: 'Land surface temperature in Celsius' },
    'LST anomaly': { expr: 'LST - __MEAN_LST__', ramp: 'rdbu', note: 'K above/below the scene mean' },
    'Cool & green': { expr: '(NIR_SR - RED_SR) / (NIR_SR + RED_SR) > 0.5 && LST < 305 ? 1 : 0', ramp: 'viridis', note: 'Vigorous, transpiring vegetation (ET proxy), 1 = yes' },
  };
  const isCalc = (l) => l.startsWith('calc:');
  const calcName = (l) => l.slice(5);

  let canvas, wrap, view;
  let stacks = $state([]);
  let stack = $state.raw(null);
  let progress = $state(0);
  let loading = $state(false);
  let error = $state('');
  let exprError = $state('');
  let tc = $state.raw(null);
  let probe = $state(null);

  // Live view controls (lighting/geometry only — never re-colour the raster)
  let ex = $state(3);
  let sunAz = $state(225), sunAlt = $state(45);

  // Draft raster settings: editing these does NOT redraw. "Regenerate raster" applies them.
  let form = $state({
    stackName: '', maxDim: 512,
    layer: 'LST', expr: CALCS['NDRE'].expr,
    ramp: 'inferno', autoStretch: true, lo: 0, hi: 1,
    maskClouds: true,
    thOn: false, thOp: '>', thVal: 0,
  });
  // What is currently drawn: a snapshot of the form + the computed values/stats
  let applied = $state.raw(null);

  const layerNames = $derived(stack ? Object.keys(stack.layers) : []);
  const dirty = $derived(!applied || JSON.stringify(form) !== JSON.stringify(applied.form));
  const layerLabel = (l) => (l === 'TRUE_COLOR' ? 'True colour' : isCalc(l) ? `${calcName(l)} (calc)` : l);

  // One entry point for the combined Layer dropdown: base raster or calculation
  function pickLayer(value) {
    form.layer = value;
    form.autoStretch = true;
    if (value === 'TRUE_COLOR') return;
    if (isCalc(value)) {
      const c = CALCS[calcName(value)];
      if (c) { form.expr = c.expr; form.ramp = c.ramp; }
      else form.ramp = 'rdbu';
    } else form.ramp = defaultRamp(value);
  }

  // Editing a preset's formula turns it into a custom calculation, so the dropdown stays truthful
  function onFormulaInput() {
    const c = CALCS[calcName(form.layer)];
    if (!c || form.expr !== c.expr) form.layer = 'calc:Custom';
  }

  let formulaEl = $state();
  function insertVar(name) {
    const el = formulaEl, a = el.selectionStart ?? form.expr.length, b = el.selectionEnd ?? a;
    form.expr = form.expr.slice(0, a) + name + form.expr.slice(b);
    onFormulaInput();
    queueMicrotask(() => { el.focus(); el.setSelectionRange(a + name.length, a + name.length); });
  }

  function histogram(values, lo, hi) {
    if (!values || !(hi > lo)) return null;
    const bins = new Array(64).fill(0);
    for (const v of values) if (Number.isFinite(v) && v >= lo && v <= hi) bins[Math.min(63, Math.floor(((v - lo) / (hi - lo)) * 64))]++;
    return { bins, max: Math.max(...bins) };
  }

  function thresholdStats(f, values) {
    if (!f.thOn || !values) return null;
    const pass = f.thOp === '>' ? (v) => v > f.thVal : (v) => v < f.thVal;
    const { LST, RED_SR, NIR_SR, DEM, CLOUD_MASK: cloud } = stack.layers;
    let n = 0, valid = 0, lst = 0, ndvi = 0, dem = 0;
    for (let i = 0; i < values.length; i++) {
      const v = values[i];
      if (!Number.isFinite(v) || (f.maskClouds && cloud?.[i] === 1)) continue;
      valid++;
      if (pass(v)) {
        n++; lst += LST?.[i] ?? 0; dem += DEM?.[i] ?? 0;
        ndvi += NIR_SR && RED_SR ? (NIR_SR[i] - RED_SR[i]) / (NIR_SR[i] + RED_SR[i]) : 0;
      }
    }
    return { n, pct: (100 * n) / valid, km2: (n * stack.res * stack.res) / 1e6, lst: lst / n, ndvi: ndvi / n, dem: dem / n };
  }

  function paint(f, values) {
    const N = stack.w * stack.h, rgb = new Float32Array(N * 3);
    if (!values) rgb.set(tc);
    else {
      const r = RAMPS[f.ramp], span = f.hi - f.lo || 1;
      const pass = f.thOp === '>' ? (v) => v > f.thVal : (v) => v < f.thVal;
      for (let i = 0; i < N; i++) {
        const v = values[i];
        let c;
        if (!Number.isFinite(v)) c = [0.2, 0.2, 0.22];
        else {
          c = sample(r, (v - f.lo) / span);
          if (f.thOn) c = pass(v) ? [0, 0.9, 1] : [c[0] * 0.35, c[1] * 0.35, c[2] * 0.35];
        }
        rgb[i * 3] = c[0]; rgb[i * 3 + 1] = c[1]; rgb[i * 3 + 2] = c[2];
      }
    }
    const cloud = stack.layers.CLOUD_MASK;
    if (f.maskClouds && cloud) for (let i = 0; i < N; i++) if (cloud[i] === 1) rgb[i * 3] = rgb[i * 3 + 1] = rgb[i * 3 + 2] = 0.92;
    view.setColors(rgb);
  }

  // The single entry point that (re)draws the raster.
  async function regenerate() {
    if (loading || !form.stackName) return;
    error = ''; exprError = '';
    if (!stack || stack.name !== form.stackName || stack.maxDim !== form.maxDim) {
      loading = true; progress = 0; probe = null;
      try {
        const s = await loadStack(form.stackName, form.maxDim, (p) => (progress = p));
        s.maxDim = form.maxDim;
        tc = trueColor(s);
        view.setStack(s);
        view.setExaggeration(ex);
        stack = s;
        if (form.layer !== 'TRUE_COLOR' && !isCalc(form.layer) && !s.layers[form.layer]) pickLayer('LST');
      } catch (e) { error = String(e); loading = false; return; }
      loading = false;
    }

    let values = null;
    if (isCalc(form.layer)) {
      try { values = evaluate(stack, form.expr.replaceAll('__MEAN_LST__', String(stack.stats.LST.mean))); }
      catch (e) { exprError = e.message; return; }
    } else if (form.layer !== 'TRUE_COLOR') values = stack.layers[form.layer];

    const st = values ? (isCalc(form.layer) ? stats(values) : stack.stats[form.layer]) : null;
    if (st?.n && form.autoStretch) {
      form.lo = +st.p2.toPrecision(4); form.hi = +st.p98.toPrecision(4);
      if (!form.thOn && applied?.form.layer !== form.layer) form.thVal = +(form.lo + (form.hi - form.lo) * 0.8).toPrecision(4);
    }
    const f = $state.snapshot(form);
    paint(f, values);
    applied = { form: f, values, stats: st, hist: histogram(values, f.lo, f.hi), th: thresholdStats(f, values) };
  }

  // Read the slider values first, unconditionally: Svelte 5 only tracks state an effect
  // actually reads, so short-circuiting on `view` (unset on the first run) would leave
  // these effects with no dependencies and they'd never re-run.
  $effect(() => {
    const e = ex, s = stack;
    if (view && s) view.setExaggeration(e);
  });
  $effect(() => {
    const az = sunAz, alt = sunAlt;
    view?.setSun(az, alt);
  });

  let down = null;
  function onPointerUp(e) {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
    const p = view.pick(e.clientX, e.clientY);
    if (!p) return;
    const vals = Object.fromEntries(layerNames.map((n) => [n, stack.layers[n][p.i]]));
    if (applied && isCalc(applied.form.layer)) vals[layerLabel(applied.form.layer)] = applied.values[p.i];
    probe = { ...p, vals };
  }

  function onKey(e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && tab === 'map') { e.preventDefault(); regenerate(); }
  }

  function saveImage() {
    const a = document.createElement('a');
    a.href = view.screenshot();
    a.download = `${stack.name}-${applied?.form.layer ?? 'drape'}.png`;
    a.click();
  }

  const fmt = (v) => (v == null || !Number.isFinite(v) ? '—' : Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(3));

  onMount(() => {
    view = new TerrainView(canvas);
    const ro = new ResizeObserver(() => view.resize(wrap.clientWidth, wrap.clientHeight));
    ro.observe(wrap);
    listStacks().then((s) => {
      stacks = s;
      if (s.length) { form.stackName = s[0]; regenerate(); }
      else error = 'No stacks found in ../data. Build one: uv run sat3d-build --preset salinas --out data/salinas';
    });
    return () => { ro.disconnect(); view.dispose(); };
  });
</script>

<svelte:window onkeydown={onKey} />

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

    <div class="controls">
    <section>
      <h2>Stack</h2>
      <div class="row">
        <select bind:value={form.stackName} disabled={loading}>
          {#each stacks as s}<option value={s}>{s}</option>{/each}
        </select>
        <select bind:value={form.maxDim} disabled={loading} title="Mesh resolution">
          <option value={256}>coarse</option><option value={512}>medium</option><option value={1024}>full</option>
        </select>
      </div>
      {#if loading}<progress value={progress}></progress>{/if}
      {#if error}<p class="err">{error}</p>{/if}
    </section>

    {#if stack}
      <section>
        <h2>Layer</h2>
        <select value={form.layer} onchange={(e) => pickLayer(e.currentTarget.value)} aria-label="Layer to drape">
          <optgroup label="Base rasters">
            <option value="TRUE_COLOR">True colour (S2)</option>
            {#each layerNames as n}<option value={n}>{n}</option>{/each}
          </optgroup>
          <optgroup label="Calculations">
            {#each Object.keys(CALCS) as k}<option value={'calc:' + k}>{k}</option>{/each}
            <option value="calc:Custom">Custom formula…</option>
          </optgroup>
        </select>

        {#if isCalc(form.layer)}
          <div class="calc">
            {#if CALCS[calcName(form.layer)]}<div class="muted">{CALCS[calcName(form.layer)].note}</div>{/if}
            <textarea rows="3" bind:this={formulaEl} bind:value={form.expr} oninput={onFormulaInput} spellcheck="false" aria-label="Formula"></textarea>
            {#if exprError}<p class="err">{exprError}</p>{/if}
            <div class="vars">
              {#each layerNames.filter((n) => n !== 'CLOUD_MASK') as n}<button type="button" onclick={() => insertVar(n)}>{n}</button>{/each}
            </div>
            <div class="muted">Click a variable to insert it. JS syntax: + − * / , Math.*, a &gt; b ? 1 : 0</div>
          </div>
        {/if}

        {#if form.layer !== 'TRUE_COLOR'}
          <div class="row">
            <select bind:value={form.ramp} aria-label="Colour ramp">{#each Object.keys(RAMPS) as r}<option>{r}</option>{/each}</select>
          </div>
          <div class="legend" style:background={cssGradient(RAMPS[form.ramp])}></div>
          <div class="row range">
            <input type="number" step="any" bind:value={form.lo} oninput={() => (form.autoStretch = false)} title="Colour range min" />
            <input type="number" step="any" bind:value={form.hi} oninput={() => (form.autoStretch = false)} title="Colour range max" />
          </div>
          <label class="chk"><input type="checkbox" bind:checked={form.autoStretch} /> Auto stretch (2–98 %)</label>
        {/if}
        <label class="chk"><input type="checkbox" bind:checked={form.maskClouds} /> Mask clouds</label>
      </section>

      {#if form.layer !== 'TRUE_COLOR'}
        <section>
          <h2>Threshold analysis</h2>
          <div class="row">
            <label class="chk"><input type="checkbox" bind:checked={form.thOn} /> highlight</label>
            <select bind:value={form.thOp}><option>&gt;</option><option>&lt;</option></select>
            <input type="number" step="any" bind:value={form.thVal} />
          </div>
        </section>
      {/if}

      {#if applied}
        <section class="result">
          <h2>Displayed · {layerLabel(applied.form.layer)}</h2>
          {#if applied.hist}
            <svg class="hist" viewBox="0 0 64 20" preserveAspectRatio="none">
              {#each applied.hist.bins as b, i}<rect x={i} y={20 - (20 * b) / applied.hist.max} width="0.9" height={(20 * b) / applied.hist.max} />{/each}
              {#if applied.form.thOn && applied.form.thVal >= applied.form.lo && applied.form.thVal <= applied.form.hi}
                {@const x = (64 * (applied.form.thVal - applied.form.lo)) / (applied.form.hi - applied.form.lo)}
                <line x1={x} x2={x} y1="0" y2="20" />
              {/if}
            </svg>
            <div class="row muted mono"><span>{fmt(applied.form.lo)}</span><span style="text-align:right">{fmt(applied.form.hi)}</span></div>
          {/if}
          {#if applied.stats?.n}
            <div class="muted mono">mean {fmt(applied.stats.mean)} · sd {fmt(applied.stats.std)} · median {fmt(applied.stats.p50)}</div>
          {/if}
          {#if applied.th}
            <div class="mono">
              {applied.form.thOp} {applied.form.thVal}: {applied.th.n.toLocaleString()} px · {applied.th.pct.toFixed(1)}% · {applied.th.km2.toFixed(2)} km²<br />
              inside: LST {fmt(applied.th.lst)} K · NDVI {fmt(applied.th.ndvi)} · elev {fmt(applied.th.dem)} m
            </div>
          {/if}
        </section>
      {/if}

      <section>
        <h2>View <span class="live">live</span></h2>
        <label>Exaggeration {ex}×<input type="range" min="1" max="10" step="0.5" bind:value={ex} /></label>
        <label>Sun azimuth {sunAz}°<input type="range" min="0" max="360" step="5" bind:value={sunAz} /></label>
        <label>Sun altitude {sunAlt}°<input type="range" min="5" max="90" step="5" bind:value={sunAlt} /></label>
      </section>

      <section>
        <h2>Probe</h2>
        {#if probe}
          <table class="mono">
            <tbody>
              <tr><td>row, col</td><td>{probe.row}, {probe.col}</td></tr>
              {#each Object.entries(probe.vals) as [k, v]}<tr class:hl={applied && (k === applied.form.layer || k === layerLabel(applied.form.layer))}><td>{k}</td><td>{fmt(v)}</td></tr>{/each}
            </tbody>
          </table>
        {:else}<div class="muted">Click the terrain to read every layer at that point.</div>{/if}
      </section>

      <section><button class="secondary" onclick={saveImage}>Save PNG</button></section>
    {/if}
    </div>

    <div class="generate" class:pending={dirty}>
      <button class="primary" onclick={regenerate} disabled={loading || !form.stackName || (!dirty && !!applied)}>
        {#if loading}Loading… {Math.round(progress * 100)}%{:else}⟳ {applied ? 'Regenerate raster' : 'Generate raster'}{/if}
      </button>
      <div class="status">
        {#if loading}Reading COGs…{:else if dirty && applied}Changes pending · Ctrl+Enter{:else if applied}Raster is up to date{:else}&nbsp;{/if}
      </div>
    </div>
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
  aside { width: 300px; flex: none; display: flex; flex-direction: column; background: var(--panel); border-right: 1px solid var(--border); }
  aside header { padding: 12px 14px 8px; }
  .controls { flex: 1; overflow-y: auto; padding: 0 14px; }
  .generate { flex: none; padding: 12px 14px 14px; border-top: 1px solid var(--border); background: var(--panel); }
  .generate.pending { box-shadow: 0 -6px 18px #0006; }
  button.primary { width: 100%; padding: 12px; font-size: 15px; font-weight: 700; letter-spacing: 0.02em; border-radius: 8px;
    background: var(--panel-2); color: var(--muted); border: 1px solid var(--border); transition: background 0.15s, color 0.15s; }
  .pending button.primary:not(:disabled) { background: var(--accent); color: #1a1205; border-color: var(--accent);
    animation: pulse 1.6s ease-in-out infinite; }
  .pending button.primary:not(:disabled):hover { filter: brightness(1.08); }
  button.primary:disabled { cursor: default; }
  @keyframes pulse { 0%, 100% { box-shadow: 0 0 0 0 #ffb45466; } 50% { box-shadow: 0 0 0 6px #ffb45400; } }
  @media (prefers-reduced-motion: reduce) { .pending button.primary { animation: none; } }
  .status { margin-top: 6px; text-align: center; font-size: 11px; color: var(--muted); }
  .pending .status { color: var(--accent); }
  optgroup { color: var(--muted); font-style: normal; } option { color: var(--fg); }
  .calc { display: flex; flex-direction: column; gap: 6px; padding: 8px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg); }
  .vars { display: flex; flex-wrap: wrap; gap: 4px; }
  .vars button { width: auto; padding: 1px 6px; font-size: 10.5px; font-family: ui-monospace, monospace; border-radius: 4px; }
  .live { font-size: 9px; padding: 1px 5px; border-radius: 3px; background: #7ee78722; color: #7ee787; margin-left: 4px; letter-spacing: 0.04em; }
  .result { background: #0f111555; margin: 0 -14px; padding-left: 14px; padding-right: 14px; }
  main { flex: 1; position: relative; min-width: 0; }
  canvas { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
  h1 { font-size: 15px; margin: 0 0 4px; }
  h2 { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 0 0 6px; }
  section { padding: 10px 0; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 6px; }
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
