"""Build a Hydrosat-L2-like layer stack from open data, on one aligned grid.

Hydrosat L2 (vz-l2) asset      -> open-data source used here
-------------------------------------------------------------------------
LST                            -> Landsat 8/9 C2 L2 ST_B10 (lwir11), kelvin
LST_UNCERTAINTY                -> Landsat C2 L2 ST_QA (qa), kelvin
LWIR1_EMIS                     -> Landsat C2 L2 ST_EMIS (emis)
LWIR2_EMIS                     -> (no open equivalent; Landsat L2 uses B10 only)
BLUE/GREEN/RED_SR              -> Sentinel-2 L2A B02/B03/B04 (10 m -> 30 m)
REDEDGE1/2/3_SR                -> Sentinel-2 L2A B05/B06/B07 (20 m -> 30 m)
NIR_SR                         -> Sentinel-2 L2A B08 (10 m -> 30 m)
CLOUD_MASK                     -> Landsat QA_PIXEL bits  OR  Sentinel-2 SCL
(extra) DEM                    -> Copernicus GLO-30 DSM, metres
(extra) NDVI                   -> derived from RED_SR / NIR_SR

Everything is warped to a common UTM 30 m grid (Hydrosat L1B/L2 use 30 m UTM)
and written as float32 COGs with physical units, plus a manifest.json.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import planetary_computer as pc
import pystac_client
import rasterio
from pyproj import CRS, Transformer
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT

PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
EARTH_SEARCH = "https://earth-search.aws.element84.com/v1"
RES = 30.0

GDAL_ENV = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    AWS_NO_SIGN_REQUEST="YES",  # Copernicus DEM / sentinel-cogs are public buckets
    GDAL_HTTP_MULTIPLEX="YES",
    VSI_CACHE="TRUE",
)

# name: (source, asset key, resampling)
LAYERS = {
    "LST": ("landsat", "lwir11", Resampling.bilinear),
    "LST_UNCERTAINTY": ("landsat", "qa", Resampling.bilinear),
    "LWIR1_EMIS": ("landsat", "emis", Resampling.bilinear),
    "BLUE_SR": ("s2", "blue", Resampling.average),
    "GREEN_SR": ("s2", "green", Resampling.average),
    "RED_SR": ("s2", "red", Resampling.average),
    "REDEDGE1_SR": ("s2", "rededge1", Resampling.bilinear),
    "REDEDGE2_SR": ("s2", "rededge2", Resampling.bilinear),
    "REDEDGE3_SR": ("s2", "rededge3", Resampling.bilinear),
    "NIR_SR": ("s2", "nir", Resampling.average),
}


def utm_grid(bbox: list[float], res: float = RES):
    """Snap a lon/lat bbox to a UTM grid. Returns (crs, transform, width, height)."""
    lon = (bbox[0] + bbox[2]) / 2
    lat = (bbox[1] + bbox[3]) / 2
    epsg = (32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1
    crs = CRS.from_epsg(epsg)
    tf = Transformer.from_crs(4326, crs, always_xy=True)
    xs, ys = tf.transform([bbox[0], bbox[2], bbox[0], bbox[2]], [bbox[1], bbox[1], bbox[3], bbox[3]])
    x0, x1 = np.floor(min(xs) / res) * res, np.ceil(max(xs) / res) * res
    y0, y1 = np.floor(min(ys) / res) * res, np.ceil(max(ys) / res) * res
    w, h = int((x1 - x0) / res), int((y1 - y0) / res)
    return crs, from_origin(x0, y1, res, res), w, h


def _read_warped(href: str, grid, resampling, band_meta: dict | None = None) -> np.ndarray:
    """Read one remote COG onto the target grid, applying scale/offset; nodata -> NaN."""
    crs, transform, w, h = grid
    with rasterio.open(href) as src:
        nodata = src.nodata if src.nodata is not None else (band_meta or {}).get("nodata")
        with WarpedVRT(src, crs=crs, transform=transform, width=w, height=h,
                       resampling=resampling, src_nodata=nodata, nodata=nodata) as vrt:
            arr = vrt.read(1).astype("float32")
    if nodata is not None:
        arr[arr == nodata] = np.nan
    meta = band_meta or {}
    return arr * meta.get("scale", 1.0) + meta.get("offset", 0.0)


def _band_meta(item, key) -> dict:
    bands = item.assets[key].to_dict().get("raster:bands") or [{}]
    return bands[0]


def find_scenes(bbox, start: str, end: str, max_cloud: float = 10, max_days_apart: int = 5):
    """Pick the clearest Landsat 8/9 L2 scene in the window and the closest clear S2 L2A scene."""
    pcat = pystac_client.Client.open(PC_STAC, modifier=pc.sign_inplace)
    ls = list(pcat.search(collections=["landsat-c2-l2"], bbox=bbox, datetime=f"{start}/{end}",
                          query={"eo:cloud_cover": {"lt": max_cloud},
                                 "platform": {"in": ["landsat-8", "landsat-9"]}}).items())
    if not ls:
        raise RuntimeError("no Landsat C2 L2 scene matches; widen dates or max_cloud")
    ecat = pystac_client.Client.open(EARTH_SEARCH)
    s2 = list(ecat.search(collections=["sentinel-2-c1-l2a"], bbox=bbox, datetime=f"{start}/{end}",
                          query={"eo:cloud_cover": {"lt": max_cloud}}).items())
    if not s2:
        raise RuntimeError("no Sentinel-2 L2A scene matches; widen dates or max_cloud")

    best = None
    for L in ls:
        for S in s2:
            gap = abs((L.datetime - S.datetime).total_seconds()) / 86400
            score = (gap > max_days_apart, gap + L.properties["eo:cloud_cover"] / 10)
            if best is None or score < best[0]:
                best = (score, L, S, gap)
    _, L, S, gap = best
    dem = list(ecat.search(collections=["cop-dem-glo-30"], bbox=bbox).items())
    return L, S, dem, gap


def cloud_mask(L, S, grid) -> np.ndarray:
    """1 = cloud / shadow / cirrus in either sensor, 0 = clear, 255 = no data."""
    q = _read_warped(L.assets["qa_pixel"].href, grid, Resampling.nearest, {"nodata": 1})
    q = np.nan_to_num(q, nan=1).astype("uint16")
    ls_cloud = (q & (1 << 1 | 1 << 2 | 1 << 3 | 1 << 4)) > 0  # dilated, cirrus, cloud, shadow
    scl = _read_warped(S.assets["scl"].href, grid, Resampling.nearest, {"nodata": 0})
    s2_cloud = np.isin(scl, [3, 8, 9, 10])  # shadow, cloud med/high, cirrus
    out = (ls_cloud | s2_cloud).astype("uint8")
    out[(q == 1) | np.isnan(scl)] = 255
    return out


def build(bbox: list[float], start: str, end: str, out_dir: str | Path,
          max_cloud: float = 10, name: str = "aoi") -> dict:
    """Build the analog stack for a lon/lat bbox and date window. Returns the manifest."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    grid = utm_grid(bbox)
    crs, transform, w, h = grid
    L, S, dems, gap = find_scenes(bbox, start, end, max_cloud)

    profile = dict(driver="COG", dtype="float32", count=1, width=w, height=h, crs=crs,
                   transform=transform, nodata=np.nan, compress="deflate", predictor=3)
    written = {}

    def write(layer, arr, **over):
        p = out / f"{layer}.tif"
        with rasterio.open(p, "w", **{**profile, **over}) as dst:
            dst.write(arr, 1)
            dst.set_band_description(1, layer)
        written[layer] = p.name

    with rasterio.Env(**GDAL_ENV):
        arrays = {}
        for layer, (src, key, rs) in LAYERS.items():
            item = L if src == "landsat" else S
            arrays[layer] = _read_warped(item.assets[key].href, grid, rs, _band_meta(item, key))
            write(layer, arrays[layer])

        write("CLOUD_MASK", cloud_mask(L, S, grid), dtype="uint8", nodata=255, predictor=1)

        dem = np.full((h, w), np.nan, dtype="float32")
        for d in dems:
            tile = _read_warped(d.assets["data"].href, grid, Resampling.bilinear)
            dem = np.where(np.isnan(dem), tile, dem)
        write("DEM", dem)

    red, nir = arrays["RED_SR"], arrays["NIR_SR"]
    with np.errstate(divide="ignore", invalid="ignore"):
        write("NDVI", ((nir - red) / (nir + red)).astype("float32"))

    manifest = {
        "name": name,
        "created": dt.datetime.now(dt.timezone.utc).isoformat(),
        "bbox_lonlat": bbox,
        "crs": crs.to_string(),
        "resolution_m": RES,
        "shape": [h, w],
        "sources": {
            "landsat": {"id": L.id, "datetime": L.datetime.isoformat(),
                        "cloud_cover": L.properties["eo:cloud_cover"]},
            "sentinel2": {"id": S.id, "datetime": S.datetime.isoformat(),
                          "cloud_cover": S.properties["eo:cloud_cover"]},
            "dem": [d.id for d in dems],
            "landsat_s2_days_apart": round(gap, 2),
        },
        "units": {"LST": "K", "LST_UNCERTAINTY": "K", "LWIR1_EMIS": "emissivity",
                  "*_SR": "reflectance", "DEM": "m (DSM, EGM2008)", "NDVI": "index",
                  "CLOUD_MASK": "0 clear / 1 cloud / 255 nodata"},
        "layers": written,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
