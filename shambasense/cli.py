"""Command line for the whole pipeline.

    python -m shambasense.cli init-db
    python -m shambasense.cli ingest-live              # NASA POWER + SoilGrids for every county
    python -m shambasense.cli load-yields FILE --format kilimostat|harveststat
    python -m shambasense.cli load-kmd FILE | load-prices FILE | load-costs FILE | load-outlooks FILE
    python -m shambasense.cli build-dataset
    python -m shambasense.cli train
    python -m shambasense.cli recommend --county machakos --season short_rains
    python -m shambasense.cli serve

    python -m shambasense.cli ingest-sample            # SYNTHETIC demo data, for testing only
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from . import config, db


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shambasense", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="create database tables")
    sub.add_parser("reset-db", help="drop and recreate all tables (deletes data)")
    p = sub.add_parser("ingest-live", help="fetch NASA POWER weather and SoilGrids soil for the counties")
    p.add_argument("--county", action="append", help="limit to these county ids")
    p.add_argument("--start-year", type=int)
    p.add_argument("--end-year", type=int)
    p = sub.add_parser("ingest-sample", help="load SYNTHETIC demo data (testing only)")
    p.add_argument("--seed", type=int, default=7)
    p = sub.add_parser("load-yields", help="load county yields")
    p.add_argument("path")
    p.add_argument("--format", choices=["kilimostat", "harveststat", "csv"], default="csv")
    for name, helptext in (("load-kmd", "KMD station weather"), ("load-prices", "KAMIS prices"),
                           ("load-costs", "production costs"), ("load-outlooks", "seasonal outlooks")):
        p = sub.add_parser(name, help=f"load {helptext}")
        p.add_argument("path")
    p = sub.add_parser("build-dataset", help="build the training table")
    p.add_argument("--out", default=None)
    p = sub.add_parser("train", help="evaluate, train and save the yield model")
    p.add_argument("--no-figures", action="store_true")
    p = sub.add_parser("recommend", help="print a recommendation")
    p.add_argument("--county")
    p.add_argument("--lat", type=float)
    p.add_argument("--lon", type=float)
    p.add_argument("--season", choices=["long_rains", "short_rains"])
    p.add_argument("--year", type=int)
    p.add_argument("--lang", choices=["en", "sw"], default="en")
    p = sub.add_parser("serve", help="run the API and web app")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    sub.add_parser("status", help="show what data is loaded")
    p = sub.add_parser("export-data", help="write county weather and soil to the data/real/ snapshot")
    p.add_argument("--dir")
    p = sub.add_parser("load-real", help="load the data/real/ snapshot (replaces SYNTHETIC data)")
    p.add_argument("--dir")
    p = sub.add_parser("create-admin", help="create (or promote) an administrator account")
    p.add_argument("--phone", required=True)
    p.add_argument("--pin", required=True)
    p.add_argument("--name", default="Administrator")
    sub.add_parser("send-reminders", help="send SMS planting reminders that are due today")
    p = sub.add_parser("bootstrap", help="prepare data, model and admin on server start (idempotent)")
    p.add_argument("--no-figures", action="store_true")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    db.init_db()

    if args.cmd == "init-db":
        print(f"database ready: {config.database_url()}")
    elif args.cmd == "reset-db":
        db.reset_db()
        print("database reset")
    elif args.cmd == "ingest-live":
        from .ingest import live

        for county_id in args.county or list(config.counties()):
            _print(live.ingest_county(county_id, args.start_year, args.end_year))
    elif args.cmd == "ingest-sample":
        from .ingest import synthetic

        _print(synthetic.generate(args.seed))
        print("SYNTHETIC test data loaded. Do not report results trained on it.")
    elif args.cmd == "load-yields":
        from .ingest import loaders

        if args.format == "harveststat":
            from .ingest import harveststat

            n = harveststat.load(args.path, log_path=config.ROOT / "reports" / "yield_cleaning_log.csv")
        elif args.format == "kilimostat":
            n = loaders.load_kilimostat(args.path)
        else:
            n = loaders.load_yields_csv(args.path)
        print(f"stored {n} yield rows")
    elif args.cmd in ("load-kmd", "load-prices", "load-costs", "load-outlooks"):
        from .ingest import loaders

        fn = {"load-kmd": loaders.load_kmd_stations, "load-prices": loaders.load_kamis,
              "load-costs": loaders.load_costs, "load-outlooks": loaders.load_outlooks}[args.cmd]
        print(f"stored {fn(args.path)} rows")
    elif args.cmd == "build-dataset":
        from .features.dataset import build_training_table, describe_table

        table = build_training_table()
        out = args.out or str(config.data_dir() / "processed" / "training_table.csv")
        config.data_dir().joinpath("processed").mkdir(exist_ok=True)
        table.to_csv(out, index=False)
        _print(describe_table(table) | {"written_to": out})
    elif args.cmd == "train":
        from .features.dataset import build_training_table
        from .models.yield_model import train_and_evaluate

        table = build_training_table()
        figures = None if args.no_figures else config.ROOT / "reports" / "figures"
        model = train_and_evaluate(table, figures)
        path = model.save()
        ev = model.meta["evaluation"]
        _print({"saved": str(path), "data_quality": model.meta["data_quality"],
                "training_rows": model.meta["training_data"]["rows"],
                "leave_one_year_out": ev.get("year"), "leave_one_county_out": ev.get("county"),
                "importance_by_group": model.meta["importance_by_group"]})
        if model.meta["data_quality"] == "synthetic":
            print("\nNOTE: trained on SYNTHETIC data. These numbers only show the pipeline works.")
    elif args.cmd == "recommend":
        from .models.registry import get_model
        from .recommend import engine

        _print(engine.recommend(lat=args.lat, lon=args.lon, county_id=args.county, season=args.season,
                                year=args.year, lang=args.lang, channel="cli", model=get_model()))
    elif args.cmd == "serve":
        import uvicorn

        uvicorn.run("shambasense.api.main:app", host=args.host, port=args.port, reload=args.reload)
    elif args.cmd == "create-admin":
        from .services import auth

        phone = auth.normalize_phone(args.phone)
        existing = db.read_df("SELECT id FROM app_user WHERE phone = :p", {"p": phone}) if phone else None
        if existing is not None and not existing.empty:
            auth.update_user(int(existing.iloc[0, 0]), is_admin=1)
            print(f"{auth.mask_phone(phone)} is now an administrator")
        else:
            user, _ = auth.register(args.phone, args.pin, args.name, is_admin=True)
            print(f"administrator created: {auth.mask_phone(user.phone)}")
    elif args.cmd == "bootstrap":
        import os

        from .models.yield_model import MODEL_FILE
        from .services import auth

        from .ingest import real

        if not config.demo_mode() and real.available() and real.needs_loading():
            print("bootstrap: loading real data from data/real/", real.load_all())
        elif db.read_df("SELECT 1 FROM climate_daily LIMIT 1").empty:
            if config.demo_mode():
                from .ingest import synthetic

                print("bootstrap: loading SYNTHETIC demo data", synthetic.generate())
            else:
                from .ingest import live

                for county_id in config.counties():
                    try:
                        print("bootstrap:", live.ingest_county(county_id))
                    except Exception as exc:  # noqa: BLE001
                        print(f"bootstrap: could not fetch {county_id}: {exc}")
        from .models.yield_model import metadata

        meta = metadata()
        wanted = "synthetic" if config.demo_mode() else "real"
        stale = meta is not None and meta.get("data_quality") != wanted and not (wanted == "real" and not real.available())
        if stale:
            print(f"bootstrap: the saved model was trained on {meta.get('data_quality')} data; retraining")
        if stale or not (config.model_dir() / MODEL_FILE).exists():
            from .features.dataset import build_training_table
            from .models.yield_model import train_and_evaluate

            try:
                figures = None if args.no_figures else config.ROOT / "reports" / "figures"
                model = train_and_evaluate(build_training_table(), figures)
                model.save()
                print("bootstrap: model trained on", model.meta["training_data"]["rows"], "rows")
            except RuntimeError as exc:
                print("bootstrap: no model yet:", exc)
        phone, pin = os.getenv("ADMIN_PHONE"), os.getenv("ADMIN_PIN")
        if phone and pin and auth.normalize_phone(phone):
            norm = auth.normalize_phone(phone)
            found = db.read_df("SELECT id FROM app_user WHERE phone = :p", {"p": norm})
            if found.empty:
                auth.register(phone, pin, "Administrator", is_admin=True)
                print("bootstrap: administrator created")
            else:
                auth.update_user(int(found.iloc[0, 0]), is_admin=1)
        print("bootstrap: done")
    elif args.cmd == "export-data":
        from .ingest import snapshot

        _print(snapshot.export(args.dir))
    elif args.cmd == "load-real":
        from .ingest import real

        _print(real.load_all(args.dir))
    elif args.cmd == "send-reminders":
        from .services import reminders

        _print(reminders.send_due())
    elif args.cmd == "status":
        q = {
            "locations": "SELECT kind, COUNT(*) AS n FROM location GROUP BY kind",
            "climate_days": "SELECT location_id, source, COUNT(*) AS days, MIN(date) AS first, MAX(date) AS last "
                            "FROM climate_daily GROUP BY location_id, source",
            "yields": "SELECT county_id, source, COUNT(*) AS rows, MIN(year) AS first, MAX(year) AS last "
                      "FROM crop_yield GROUP BY county_id, source",
            "prices": "SELECT source, COUNT(*) AS rows FROM market_price GROUP BY source",
            "costs": "SELECT source, COUNT(*) AS rows FROM production_cost GROUP BY source",
            "outlooks": "SELECT county_id, year, season, source FROM seasonal_outlook",
            "recommendations_logged": "SELECT channel, COUNT(*) AS n FROM recommendation_log GROUP BY channel",
        }
        for name, sql in q.items():
            print(f"\n== {name}")
            print(db.read_df(sql).to_string(index=False) or "(none)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
