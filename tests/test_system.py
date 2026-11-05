"""System tests on SYNTHETIC data: training table, model, recommendation engine, API and USSD."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest


def test_training_table_has_features(table):
    assert len(table) > 200
    for col in ("rain_mm", "tmean_c", "ph", "suitability", "onset_delay_days", "yield_t_ha"):
        assert table[col].notna().mean() > 0.95, col
    assert set(table["county_id"]) == {"trans_nzoia", "nakuru", "meru", "machakos"}


def test_model_quantiles_are_ordered_and_save_load(model, table, env):
    from shambasense.models.yield_model import YieldModel

    q = model.predict(table.head(50))
    assert (q["p10"] <= q["p50"]).all() and (q["p50"] <= q["p90"]).all() and (q["p10"] >= 0).all()
    loaded = YieldModel.load()
    assert np.allclose(loaded.predict(table.head(5)).to_numpy(), q.head(5).to_numpy())


def test_cross_validation_beats_baseline(table):
    from shambasense.models.yield_model import cross_validate

    small = table[table["year"] >= 2016]
    metrics, preds = cross_validate(small, "year")
    assert metrics["shambasense"]["mae_t_ha"] < metrics["baseline"]["mae_t_ha"]
    assert {"p10", "p90", "baseline", "ridge", "random_forest"} <= set(preds.columns)


def test_analog_weights_follow_outlook():
    from shambasense.recommend.forecast import analog_weights

    cats = pd.Series([0, 0, 1, 1, 1, 2])
    w = analog_weights(cats, {"p_below": 0.5, "p_normal": 0.3, "p_above": 0.2})
    assert w.sum() == pytest.approx(1)
    assert w[cats == 0].sum() == pytest.approx(0.5) and w[cats == 2].sum() == pytest.approx(0.2)


def test_default_season():
    from shambasense.recommend.engine import default_season, next_year_for

    assert default_season("machakos", date(2026, 11, 5)) == ("long_rains", 2027)
    assert default_season("machakos", date(2026, 7, 1)) == ("short_rains", 2026)
    assert default_season("trans_nzoia", date(2026, 11, 5)) == ("long_rains", 2027)
    assert next_year_for("meru", "short_rains", date(2026, 9, 20)) == 2026


def test_recommendation_structure(model):
    from shambasense.recommend import engine

    r = engine.recommend(county_id="machakos", season="short_rains", year=2027, model=model, log_request=False)
    recs = r["recommendations"]
    assert recs and [c["rank"] for c in recs] == list(range(1, len(recs) + 1))
    assert [c["tier"] for c in recs] == sorted(c["tier"] for c in recs)
    top = recs[0]
    assert top["yield_t_ha"]["p10"] <= top["yield_t_ha"]["p50"] <= top["yield_t_ha"]["p90"]
    assert "gross_margin_kes_ha" in top and 0 <= top["prob_loss"] <= 1
    pw = r["planting_window"]
    assert pw["early"] <= pw["median"] <= pw["late"] and pw["early"].startswith("2027-1")
    assert any("SYNTHETIC" in w for w in r["warnings"])
    assert r["analog_seasons"] >= 25


def test_dry_outlook_lowers_expected_yields(model):
    from shambasense.recommend import engine

    kw = dict(county_id="machakos", season="long_rains", year=2027, model=model, log_request=False)
    dry = engine.recommend(forecast={"p_below": 0.8, "p_normal": 0.15, "p_above": 0.05, "source": "test"}, **kw)
    wet = engine.recommend(forecast={"p_below": 0.05, "p_normal": 0.15, "p_above": 0.8, "source": "test"}, **kw)
    y = lambda r, c: next((x["yield_t_ha"]["p50"] for x in r["recommendations"] if x["crop"] == c), 0)  # noqa: E731
    assert y(dry, "beans") < y(wet, "beans")


def test_point_falls_back_to_county_when_offline(model):
    from shambasense.recommend import engine

    r = engine.recommend(lat=-1.40, lon=37.40, season="short_rains", year=2027, model=model, log_request=False)
    assert r["location"]["county"] == "machakos" and r["location"]["data_level"] == "county"
    assert any("county averages" in w for w in r["warnings"])


def test_swahili_output(model):
    from shambasense.recommend import engine

    r = engine.recommend(county_id="meru", season="long_rains", year=2027, lang="sw", model=model, log_request=False)
    assert r["season_name"] == "Mvua ndefu"
    assert r["planting_window"]["advice"].startswith("Panda")


# ------------------------------------------------------------------------------- API + USSD

@pytest.fixture(scope="module")
def client(model):
    from fastapi.testclient import TestClient

    from shambasense.api.main import app

    with TestClient(app) as c:
        yield c


def test_health_and_reference(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["model_loaded"] and h["data_quality"] == "synthetic"
    assert len(client.get("/api/counties").json()) == 4
    assert {c["id"] for c in client.get("/api/crops").json()} >= {"maize", "beans", "sorghum"}


def test_recommend_endpoint(client):
    res = client.post("/api/recommend", json={"county": "nakuru", "season": "long_rains", "year": 2027})
    assert res.status_code == 200 and res.json()["recommendations"]
    assert client.post("/api/recommend", json={"lat": 1.0}).status_code == 422
    bad_season = client.post("/api/recommend", json={"county": "trans_nzoia", "season": "short_rains"})
    assert bad_season.status_code == 400
    bad_outlook = client.post("/api/recommend", json={"county": "meru", "outlook": {"p_below": 0.9, "p_normal": 0.9, "p_above": 0.1}})
    assert bad_outlook.status_code == 422


def test_admin_outlook_requires_token(client):
    body = {"county": "meru", "year": 2032, "season": "long_rains", "p_below": 0.2, "p_normal": 0.3, "p_above": 0.5}
    assert client.post("/api/admin/outlook", json=body).status_code == 401
    assert client.post("/api/admin/outlook", json=body, headers={"X-Admin-Token": "test-token"}).json() == {"saved": True}
    o = client.get("/api/outlook/meru", params={"season": "long_rains", "year": 2032}).json()
    assert o["forecast"]["p_above"] == pytest.approx(0.5)


def test_feedback(client):
    from shambasense import db

    res = client.post("/api/feedback", json={"county": "meru", "season": "long_rains", "year": 2027,
                                             "crop": "beans", "rating": 4, "yield_bags_acre": 6})
    assert res.json() == {"saved": True}
    assert not db.read_df("SELECT * FROM feedback WHERE crop = 'beans'").empty


def test_ussd_flow(client):
    from shambasense import db

    post = lambda text: client.post("/ussd", data={"sessionId": "s1", "serviceCode": "*384*1#",  # noqa: E731
                                                   "phoneNumber": "+254700000001", "text": text}).text
    assert post("").startswith("CON") and "Kiswahili" in post("")
    assert "Machakos" in post("1")
    assert post("1*4").startswith("CON")
    final = post("1*4*2")
    assert final.startswith("END") and len(final) <= 182 and "1." in final
    assert post("2*1").startswith("END")          # Trans Nzoia has one season: straight to advice
    assert post("9").startswith("END")
    logged = db.read_df("SELECT user_hash FROM recommendation_log WHERE channel = 'ussd'")
    assert not logged.empty and not logged["user_hash"].str.contains("254").any()   # phone never stored


def test_web_app_served(client):
    assert "ShambaSense" in client.get("/").text
    assert client.get("/static/js/app.js").status_code == 200
    assert "ShambaSense" in client.get("/admin").text
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]
    manifest = client.get("/manifest.webmanifest").json()
    assert manifest["display"] == "standalone" and any(i["purpose"] == "maskable" for i in manifest["icons"])
    for icon in manifest["icons"]:
        assert client.get(icon["src"]).status_code == 200
