"""CLI: `sat3d-build` builds an analog stack and its 3D viewer."""

import argparse
import json

from sat3d.analog import build
from sat3d.drape import export_html

PRESETS = {
    # name: (bbox lon/lat, start, end) — ag fields against the Gabilan/Santa Lucia ranges
    "salinas": ([-121.75, 36.5, -121.5, 36.7], "2024-07-01", "2024-08-31"),
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preset", choices=PRESETS)
    ap.add_argument("--bbox", type=float, nargs=4, metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"))
    ap.add_argument("--start"), ap.add_argument("--end")
    ap.add_argument("--name", default="aoi")
    ap.add_argument("--max-cloud", type=float, default=10)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.preset:
        bbox, start, end = PRESETS[a.preset]
        a.name = a.name if a.name != "aoi" else a.preset
    else:
        bbox, start, end = a.bbox, a.start, a.end
        if not (bbox and start and end):
            ap.error("give --preset or all of --bbox/--start/--end")
    m = build(bbox, start, end, a.out, max_cloud=a.max_cloud, name=a.name)
    print(json.dumps(m["sources"], indent=2))
    print("viewer:", export_html(a.out))


if __name__ == "__main__":
    main()
