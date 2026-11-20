<script>
  // Diagram of the sat3d tech stack as built today, plus the planned scaling path.
  const W = 180;
  const X = [20, 245, 470, 695, 920];
  const columns = ['Sources', 'Build · Python', 'Storage', 'Serve', 'Client'];

  const boxes = [
    { x: X[0], y: 60, h: 80, kind: 'src', title: 'Landsat 8/9 C2 L2', lines: ['Planetary Computer STAC', 'LST · ST_QA · emis · QA'] },
    { x: X[0], y: 160, h: 80, kind: 'src', title: 'Sentinel-2 L2A', lines: ['Element84 Earth Search', 'SR + 3 red-edge · SCL'] },
    { x: X[0], y: 260, h: 80, kind: 'src', title: 'Copernicus GLO-30', lines: ['AWS open data (COG)', '30 m DSM'] },
    { x: X[1], y: 60, h: 280, kind: 'py', title: 'sat3d.analog', lines: ['CLI: sat3d-build', '', 'pystac-client  STAC search', 'planetary-computer  signing', 'rasterio / GDAL', '  windowed WarpedVRT', 'pyproj  UTM 30 m grid', 'numpy  scale · NDVI'] },
    { x: X[2], y: 120, h: 150, kind: 'store', title: 'data/<aoi>/', lines: ['15 float32 COGs', '30 m UTM · SI units', 'LST … NDVI · DEM', 'manifest.json'] },
    { x: X[3], y: 60, h: 90, kind: 'serve', title: 'Vite dev server', lines: ['/api/stacks', '/data/*  HTTP Range'] },
    { x: X[3], y: 200, h: 90, kind: 'serve', title: 'viewer.html', lines: ['sat3d.drape export', 'single file · three.js'] },
    { x: X[3], y: 380, h: 100, kind: 'serve', title: 'sat3d MCP server', lines: ['mcp SDK · MCPServer', 'stdio · 4 tools'] },
    { x: X[4], y: 60, h: 280, kind: 'client', title: 'Svelte 5 app', lines: ['geotiff.js  COG decode', 'runes  reactive state', '', 'band math · threshold', 'histogram · probe', '', 'three.js  WebGL mesh', 'orbit · hillshade'] },
    { x: X[4], y: 380, h: 100, kind: 'client', title: 'Claude Code', lines: ['MCP client', 'builds stacks · stats'] },
  ];

  const arrows = [
    { d: `M200 100 H245` }, { d: `M200 200 H245` }, { d: `M200 300 H245` },
    { d: `M425 195 H470`, label: 'write', lx: 447, ly: 187 },
    { d: `M650 160 C672 160 672 105 695 105` },
    { d: `M650 230 C672 230 672 245 695 245` },
    { d: `M875 105 H920`, label: 'Range', lx: 897, ly: 97 },
    { d: `M600 270 V415 H695`, label: 'raster_info · band_stats', lx: 608, ly: 340, anchor: 'start' },
    { d: `M695 455 H335 V340`, label: 'build_analog_stack', lx: 480, ly: 447 },
    { d: `M875 430 H920`, both: true },
  ];

  const scale = [
    { title: 'Now · laptop', current: true, lines: ['COG stack on disk', 'Svelte + three.js mesh', 'analysis in browser / numpy'] },
    { title: 'Medium · web service', lines: ['STAC catalog + TiTiler', 'band-math tiles + terrain-RGB', 'MapLibre / deck.gl TerrainLayer'] },
    { title: 'Large · continental', lines: ['CesiumJS quantized-mesh', 'Zarr datacubes in object storage', 'Dask / serverless TiTiler'] },
  ];
</script>

<div class="wrap">
  <h2>How sat3d fits together</h2>
  <p class="muted">Open satellite data is built into an aligned COG stack, which the browser app, the standalone viewer and the MCP server all read.</p>

  <svg viewBox="0 0 1120 660" role="img" aria-label="sat3d tech stack diagram">
    <defs>
      <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0 0 L10 5 L0 10 z" class="arrowhead" />
      </marker>
    </defs>

    {#each columns as c, i}
      <text x={X[i] + W / 2} y="38" class="colhead" text-anchor="middle">{c.toUpperCase()}</text>
    {/each}

    {#each arrows as a}
      <path d={a.d} class="edge" marker-end="url(#arrow)" marker-start={a.both ? 'url(#arrow)' : null} />
      {#if a.label}<text x={a.lx} y={a.ly} class="edgelabel" text-anchor={a.anchor ?? 'middle'}>{a.label}</text>{/if}
    {/each}

    {#each boxes as b}
      <g class="box {b.kind}">
        <rect x={b.x} y={b.y} width={W} height={b.h} rx="8" />
        <rect x={b.x} y={b.y} width="4" height={b.h} rx="2" class="stripe" />
        <text x={b.x + 14} y={b.y + 24} class="title">{b.title}</text>
        {#each b.lines as l, i}<text x={b.x + 14} y={b.y + 46 + i * 17} class="line">{l}</text>{/each}
      </g>
    {/each}

    <text x="20" y="535" class="colhead">SCALING PATH</text>
    {#each scale as s, i}
      <g class="stage" class:current={s.current}>
        <rect x={20 + i * 370} y="550" width="340" height="90" rx="8" />
        <text x={36 + i * 370} y="574" class="title">{s.title}</text>
        {#each s.lines as l, j}<text x={36 + i * 370} y={594 + j * 16} class="line">{l}</text>{/each}
      </g>
      {#if i < scale.length - 1}<path d="M{362 + i * 370} 595 H{388 + i * 370}" class="edge dashed" marker-end="url(#arrow)" />{/if}
    {/each}
  </svg>

  <div class="legend">
    <span class="src">open data</span><span class="py">Python</span><span class="store">files</span><span class="serve">servers / exports</span><span class="client">clients</span>
  </div>
</div>

<style>
  .wrap { height: 100%; overflow: auto; padding: 24px 16px 32px; max-width: 1160px; margin: 0 auto; }
  h2 { margin: 0 0 4px; font-size: 18px; }
  .muted { color: var(--muted); margin: 0 0 16px; }
  svg { width: 100%; height: auto; min-width: 720px; display: block; }
  .colhead { fill: var(--muted); font-size: 11px; letter-spacing: 0.08em; font-weight: 600; }
  .box rect, .stage rect { fill: var(--panel); stroke: var(--border); }
  .title { fill: var(--fg); font-size: 14px; font-weight: 600; }
  .line { fill: var(--muted); font-size: 11px; font-family: ui-monospace, monospace; white-space: pre; }
  .edge { fill: none; stroke: #6b7385; stroke-width: 1.5; }
  .edge.dashed { stroke-dasharray: 4 4; }
  .arrowhead { fill: #6b7385; }
  .edgelabel { fill: var(--muted); font-size: 10.5px; }
  .src { --c: #58a6ff; } .py { --c: #ffb454; } .store { --c: #a5adbb; } .serve { --c: #c792ea; } .client { --c: #7ee787; }
  .box .stripe { fill: var(--c); stroke: none; }
  .stage rect { stroke-dasharray: 5 4; }
  .stage.current rect { stroke: var(--accent); stroke-dasharray: none; }
  .legend { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 12px; color: var(--muted); font-size: 12px; }
  .legend span::before { content: ''; display: inline-block; width: 10px; height: 10px; border-radius: 2px; background: var(--c); margin-right: 6px; vertical-align: -1px; }
</style>
