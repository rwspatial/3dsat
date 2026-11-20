"""sat3d MCP server: tools for multiband satellite imagery and 3D integration.

Raster paths can be local files or any GDAL-readable URI (e.g. /vsicurl/https://...
for Cloud-Optimized GeoTIFFs, read with range requests).
"""

from __future__ import annotations

import os

import numpy as np
import rasterio
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("sat3d")


def _env():
    # Keep GDAL from listing remote "directories" when opening one file.
    return rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", AWS_NO_SIGN_REQUEST=os.environ.get("AWS_NO_SIGN_REQUEST", "NO"))


# ------------------------------------------------------------ raster tools


@mcp.tool()
def raster_info(path: str) -> dict:
    """Describe a raster (local path or GDAL URI): size, bands, CRS, bounds, COG layout."""
    with _env(), rasterio.open(path) as ds:
        return {
            "driver": ds.driver,
            "width": ds.width,
            "height": ds.height,
            "count": ds.count,
            "dtypes": list(ds.dtypes),
            "crs": ds.crs.to_string() if ds.crs else None,
            "bounds": list(ds.bounds),
            "resolution": list(ds.res),
            "nodata": ds.nodata,
            "band_descriptions": list(ds.descriptions),
            "block_shapes": [list(s) for s in ds.block_shapes],
            "overviews": ds.overviews(1),
            "tags": ds.tags(),
        }


@mcp.tool()
def band_stats(path: str, bands: list[int] | None = None, overview_level: int | None = None) -> list[dict]:
    """Per-band min/max/mean/std/percentiles. Use overview_level (0 = first overview)
    to compute on a downsampled overview for large/remote files."""
    kwargs = {"overview_level": overview_level} if overview_level is not None else {}
    with _env(), rasterio.open(path, **kwargs) as ds:
        out = []
        for b in bands or range(1, ds.count + 1):
            arr = ds.read(b, masked=True).compressed().astype("float64")
            if arr.size == 0:
                out.append({"band": b, "valid_pixels": 0})
                continue
            p2, p50, p98 = np.percentile(arr, [2, 50, 98])
            out.append({
                "band": b,
                "description": ds.descriptions[b - 1],
                "valid_pixels": int(arr.size),
                "min": float(arr.min()), "max": float(arr.max()),
                "mean": float(arr.mean()), "std": float(arr.std()),
                "p2": float(p2), "median": float(p50), "p98": float(p98),
            })
        return out


# ------------------------------------------------------- analog + 3D tools


@mcp.tool()
def build_analog_stack(bbox: list[float], start: str, end: str, out_dir: str,
                       max_cloud: float = 10, name: str = "aoi") -> dict:
    """Build a Hydrosat-L2-like stack (LST, LST uncertainty, emissivity, 7 VNIR SR bands
    incl. 3 red-edge, cloud mask, NDVI, DEM) from Landsat C2 L2 + Sentinel-2 L2A +
    Copernicus GLO-30, on one 30 m UTM grid. bbox = [min_lon, min_lat, max_lon, max_lat];
    start/end = YYYY-MM-DD. Returns the manifest (scene ids, CRS, layers)."""
    from sat3d.analog import build
    return build(bbox, start, end, out_dir, max_cloud=max_cloud, name=name)


@mcp.tool()
def export_drape_viewer(stack_dir: str, max_dim: int = 400) -> str:
    """Write an interactive 3D HTML viewer (DEM mesh with layers draped, click-to-probe,
    threshold analysis) for a stack built by build_analog_stack. Returns the HTML path."""
    from sat3d.drape import export_html
    return str(export_html(stack_dir, max_dim=max_dim))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
