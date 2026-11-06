"""Download WFP market prices for Kenya from the Humanitarian Data Exchange (HDX).

Keeps the rows for the ShambaSense crops (maize, beans, sorghum, potatoes, green grams, tomatoes)
in WFP's own columns; scripts/prepare_prices.py turns them into data/real/market_prices.csv.

    python scripts/fetch_wfp_prices.py data/real/wfp_food_prices_kenya.csv

Source: World Food Programme, VAM food prices (HDX dataset "wfp-food-prices-for-kenya", CC BY-IGO).
"""

import csv
import io
import re
import sys

import requests

API = "https://data.humdata.org/api/3/action/package_show"
KEEP = re.compile(r"maize|bean|sorghum|potato|gram|tomato", re.I)


def main(out_path: str) -> None:
    meta = requests.get(API, params={"id": "wfp-food-prices-for-kenya"}, timeout=60).json()["result"]
    urls = [r["url"] for r in meta["resources"] if r.get("format", "").lower() == "csv" or r["url"].endswith(".csv")]
    if not urls:
        raise SystemExit("no CSV resource on HDX")
    text = requests.get(urls[0], timeout=180).text
    rows = list(csv.DictReader(io.StringIO(text)))
    rows = [r for r in rows if not r.get("date", "").startswith("#")]   # HXL tag row
    kept = [r for r in rows if KEEP.search(r.get("commodity", ""))]
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(kept)
    print(f"WFP Kenya: {len(rows)} rows on HDX, kept {len(kept)} for the study crops -> {out_path} (from {urls[0]})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/real/wfp_food_prices_kenya.csv")
