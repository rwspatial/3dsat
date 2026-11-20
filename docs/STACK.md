# Hydrosat analog data + 3D draping/analysis stack

## 1. What Hydrosat delivers (from satdocs.hydrosat.com)

Sample sets exist for five use cases (Agriculture, Energy/Industrial, General, Urban Heat, Wildfire), served as "downloadable" items via their Discovery Portal and a **STAC API**. Every raster is a **COG**.

| Level | STAC collection(s) | Content | Grid |
|---|---|---|---|
| L1A | `vz-viri-l1a`, `vz-liri-l1a`, `vz-liri-l1a-night` | At-sensor radiance: BLUE, GREEN, RED, REDEDGE1-3, NIR, LWIR1, LWIR2 + QA, preview, MTA json | EPSG:4326, VNIR 29.9 m / LWIR 68.8 m |
| L1B | `vz-l1b`, `vz-l1b-night` | TOA reflectance + brightness temperature, CLOUD_MASK, QA; DEM-orthorectified, co-registered | 30 m UTM, 70×70 km |
| L2 | `vz-l2` (day only) | **LST**, LST_UNCERTAINTY, 7× *_SR, LWIR1/2_EMIS, CLOUD_MASK, QA | 30 m UTM, 70×70 km |

So their main product is a **thermal + VNIR (with red-edge) stack on a 30 m UTM grid, with per-pixel LST uncertainty**.

## 2. Open-data analog (implemented in `src/sat3d/analog.py`)

| Hydrosat L2 asset | Analog | Notes |
|---|---|---|
| LST | Landsat 8/9 C2 L2 `ST_B10` | 100 m native TIRS, delivered at 30 m. Hydrosat's selling point is sharper thermal + more revisits |
| LST_UNCERTAINTY | Landsat `ST_QA` | Same concept (K) |
| LWIR1_EMIS | Landsat `ST_EMIS` (ASTER GED-based) | No LWIR2 equivalent (Landsat L2 uses one band) |
| *_SR (B, G, R, NIR) | Sentinel-2 L2A B02/03/04/08 | 10 m, aggregated to 30 m |
| REDEDGE1-3_SR | Sentinel-2 L2A B05/06/07 | 20 m. Landsat has no red-edge, which is why S2 is used |
| CLOUD_MASK | Landsat QA_PIXEL ∪ S2 SCL | |
| (extra) DEM | Copernicus GLO-30 DSM | The same class of DEM Hydrosat uses to orthorectify |

Sources: Landsat from Microsoft Planetary Computer (free, auto-signed). S2 and the DEM from Element84 Earth Search / AWS open buckets (no credentials). The builder picks the closest Landsat/S2 pair. For Salinas Valley, 2024-08-21, they are 24 minutes apart. Landsat 9 and S2A share the same morning orbit, so near-simultaneous pairs are common.

Other analogs worth adding later: **ECOSTRESS** (70 m LST, varying time of day, diurnal like Hydrosat's), **Landsat night scenes** (for `vz-l1b-night`), and **OpenET** ET rasters for downstream ag products.

## 3. Draping + interactive analysis: options by scale

What we need: imagery/analysis layers draped on a DEM in an interactive 3D view, with analysis (band math, thresholds, zonal stats, time series) running against the same data.

### Small scale (one AOI, a few scenes; laptop) — *what exists now*
- **Data**: aligned COG stack on disk (`sat3d-build`). 20×20 km ≈ 25 MB.
- **3D**: self-contained three.js viewer (`viewer.html`). DEM mesh, layers as vertex colours, click-probe, threshold → area. No server.
- **Analysis**: numpy/xarray in Python. Claude drives it through the MCP tools.
- Alternatives at this scale: **PyVista + trame** (Python-native 3D in Jupyter, analyses in the same process), **QGIS 3D view**, **Blender** (BlenderGIS) for presentation renders.
- Limits: whole AOI in memory and in the HTML. Practical up to ~1–2k px per side.

### Medium (many AOIs, time series, shareable web app)
- **Tiling server: [TiTiler](https://developmentseed.org/titiler/)** over COGs/STAC. It serves
  - imagery tiles with on-the-fly **band-math `expression`** (NDVI, LST thresholds, anomalies) + colormaps, and
  - the **DEM as terrain-RGB / Terrarium tiles** (`algorithm=terrainrgb`).
  One service gives both the drape and the terrain.
- **3D client**: **MapLibre GL JS** (`raster-dem` terrain + raster layer) for the lightest path. Or **deck.gl `TerrainLayer`** (elevation tiles + texture tiles, GPU picking, easy custom shaders).
- **Analysis**: xarray + `odc-stac`/`stackstac` (lazy STAC → datacube) behind a small API. Zonal stats, time series, anomaly maps written back as COGs, which TiTiler then serves.
- Catalog: a local **STAC** (static JSON or `stac-fastapi` + pgstac) so our derived products sit beside the analog and Hydrosat items. Hydrosat items drop in unchanged because they are STAC + COG too.

### Large scale (continental, many dates, many users)
- **Storage**: COGs for imagery, **Zarr** (or Icechunk) datacubes for time-series analysis, both in object storage.
- **Compute**: Dask (Coiled/Kubernetes) or serverless (titiler on Lambda, `titiler-pgstac` for mosaics). Optionally Google Earth Engine for exploration. Openness and cost are the trade-off.
- **3D**: **CesiumJS** with **quantized-mesh** terrain (e.g. Cesium World Terrain, or self-built with `cesium-terrain-builder`/`ctod`) and imagery from TiTiler as `UrlTemplateImageryProvider`. Cesium handles globe-scale streaming, time-dynamic layers (the clock slider fits multi-date LST) and **3D Tiles** if buildings or point clouds come in (urban heat use case).
- deck.gl `TerrainLayer`/`Tile3DLayer` is the lighter, more flexible alternative if a full globe isn't needed.

### Recommendation
Go **small → medium on one consistent backbone: STAC + COG + TiTiler**. Use MapLibre or deck.gl for 3D now, and move to Cesium only if globe-scale or 3D Tiles matter. Hydrosat's own delivery is STAC + COG, so the same stack can serve their data as soon as there's access. The MCP server is the analysis/agent layer on top: search, build, stats, derive products, emit viewer/tile URLs.

## 4. Next steps
1. `docker run` TiTiler locally. Point a MapLibre 3D page at the Salinas stack (DEM as terrain-RGB, LST/NDVI via `expression`).
2. MCP tools: `stac_search`, `zonal_stats(geojson)`, `derive(expression)` → COG, `time_series(bbox, layer)`.
3. Add ECOSTRESS + night Landsat to mirror Hydrosat's diurnal/night products.
4. Get the Hydrosat Agriculture sample via their STAC API and diff it against the analog for the same AOI/date.
