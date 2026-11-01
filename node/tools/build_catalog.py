"""Build stars.json (the star-route catalog) from the HYG star database.

The built-in catalog has ~50 nearby systems with approximate positions. For a
real network, download the HYG database CSV (https://github.com/astronexus/HYG-Database,
CC BY-SA 4.0) and run:

  python tools/build_catalog.py hygdata_v41.csv --max-ly 50 -o stars.json

Put stars.json next to node.py on EVERY node and delete each node's data/ folder:
the catalog is part of consensus, and changing it starts a new chain.
"""
import argparse
import csv
import json

PC_TO_LY = 3.26156


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="HYG database CSV")
    ap.add_argument("--max-ly", type=float, default=50.0, help="include stars closer than this")
    ap.add_argument("-o", "--out", default="stars.json")
    args = ap.parse_args()

    stars = []
    with open(args.csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                dist_ly = float(row["dist"]) * PC_TO_LY
            except (KeyError, ValueError):
                continue
            if dist_ly <= 0 or dist_ly > args.max_ly or float(row["dist"]) >= 100000:
                continue  # skip the Sun and stars with unknown distance
            name = (row.get("proper") or row.get("gl") or
                    (f"HIP {row['hip']}" if row.get("hip") else f"HYG {row['id']}")).strip()
            stars.append({
                "name": name,
                "x": round(float(row["x"]) * PC_TO_LY * 1000),
                "y": round(float(row["y"]) * PC_TO_LY * 1000),
                "z": round(float(row["z"]) * PC_TO_LY * 1000),
            })

    stars.sort(key=lambda s: (s["x"] ** 2 + s["y"] ** 2 + s["z"] ** 2, s["name"]))
    with open(args.out, "w") as f:
        json.dump(stars, f, indent=0)
    print(f"Wrote {len(stars)} stars within {args.max_ly} ly to {args.out}")


if __name__ == "__main__":
    main()
