"""Unit tests for suitability rules, climate features, parsers and loaders."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from shambasense.features.climate import DailySeries, detect_onset, longest_run, season_window, window_features
from shambasense.ingest import nasa_power, open_meteo, soilgrids
from shambasense.models.suitability import score, trapezoid

R = {"abs_min": 200, "opt_min": 300, "opt_max": 500, "abs_max": 900}


@pytest.mark.parametrize("value, expected", [(150, 0.0), (200, 0.0), (250, 0.5), (300, 1.0), (450, 1.0),
                                             (700, 0.5), (900, 0.0), (None, None)])
def test_trapezoid(value, expected):
    assert trapezoid(value, R) == expected


def test_score_reports_limiting_factor(env):
    result = score("beans", rain_mm=250, tmean_c=20, ph=6.0)     # rain below optimum, rest fine
    assert result["limiting"] == "rain_mm"
    assert result["score"] == pytest.approx(0.5)


def test_season_window_wraps_year():
    assert season_window(2024, [3, 4, 5]) == (date(2024, 3, 1), date(2024, 5, 31))
    assert season_window(2024, [10, 11, 12]) == (date(2024, 10, 1), date(2024, 12, 31))
    assert season_window(2024, [11, 12, 1]) == (date(2024, 11, 1), date(2025, 1, 31))


def test_longest_run():
    assert longest_run(np.array([1, 1, 0, 1, 1, 1, 0], dtype=bool)) == 3
    assert longest_run(np.array([], dtype=bool)) == 0


def _series(rain_by_day: dict[int, float], start=date(2020, 1, 1), days=400) -> DailySeries:
    dates = pd.date_range(start, periods=days, freq="D")
    rain = np.zeros(days)
    for i, mm in rain_by_day.items():
        rain[i] = mm
    return DailySeries.from_frame(pd.DataFrame({"date": dates, "rain_mm": rain, "tmean_c": 20.0,
                                                "tmax_c": 26.0, "tmin_c": 14.0}))


def test_onset_needs_wet_spell_without_long_dry_spell(env):
    # Mar 1 2020 is day 60. A false start on day 65 is followed by 10 dry days;
    # the real onset on day 80 is followed by rain every 4 days.
    rain = {65: 25.0}
    rain.update({80: 12.0, 81: 10.0})
    rain.update({d: 5.0 for d in range(84, 140, 4)})
    onset = detect_onset(_series(rain), date(2020, 3, 1))
    assert onset == date(2020, 3, 21)          # day 80


def test_window_features():
    s = _series({d: 10.0 for d in range(100, 110)})
    f = window_features(s, date(2020, 4, 9), 20)   # day 99..118
    assert f["rain_mm"] == pytest.approx(100.0)
    assert f["rain_days"] == 10
    assert f["max_dry_spell"] == 9
    assert f["coverage"] == 1.0


def test_nasa_power_parse():
    payload = {"header": {"fill_value": -999.0}, "properties": {"parameter": {
        "PRECTOTCORR": {"20240101": 1.5, "20240102": -999.0},
        "T2M": {"20240101": 20.1, "20240102": 21.0},
        "T2M_MAX": {"20240101": 26.0, "20240102": 27.0},
        "T2M_MIN": {"20240101": 14.0, "20240102": 15.0}}}}
    df = nasa_power.parse(payload)
    assert list(df.columns) == ["date", "rain_mm", "tmean_c", "tmax_c", "tmin_c"]
    assert df["rain_mm"].iloc[0] == 1.5 and np.isnan(df["rain_mm"].iloc[1])


def test_soilgrids_parse_uses_d_factor_and_depth_weights():
    def layer(name, d, values):
        depths = [{"range": {"top_depth": t, "bottom_depth": b, "unit_depth": "cm"}, "label": f"{t}-{b}cm",
                   "values": {"mean": v}} for (t, b), v in zip([(0, 5), (5, 15), (15, 30)], values)]
        return {"name": name, "unit_measure": {"d_factor": d}, "depths": depths}
    payload = {"properties": {"layers": [layer("phh2o", 10, [60, 60, 66]), layer("clay", 10, [300, 300, 300]),
                                         layer("nitrogen", 100, [200, None, 100])]}}
    out = soilgrids.parse(payload)
    assert out["ph"] == pytest.approx((6.0 * 5 + 6.0 * 10 + 6.6 * 15) / 30)
    assert out["clay_pct"] == pytest.approx(30.0)
    assert out["nitrogen_g_kg"] == pytest.approx((2.0 * 5 + 1.0 * 15) / 20)


def test_open_meteo_terciles_and_trust():
    idx = pd.date_range("2027-03-01", "2027-05-31", freq="D")
    payload = {"daily": {"time": [d.strftime("%Y-%m-%d") for d in idx],
                         "precipitation_sum": [1.0] * len(idx),            # 92 mm: below
                         "precipitation_sum_member01": [3.0] * len(idx),   # 276 mm: normal
                         "precipitation_sum_member02": [5.0] * len(idx),   # 460 mm: above
                         "precipitation_sum_member03": [0.5] * len(idx)}}  # 46 mm: below
    members = open_meteo.parse_members(payload)
    assert members.shape[1] == 4
    probs = open_meteo.tercile_probabilities(members, (date(2027, 3, 1), date(2027, 5, 31)), 150, 400, trust=1.0)
    assert (probs["p_below"], probs["p_normal"], probs["p_above"]) == (0.5, 0.25, 0.25)
    shrunk = open_meteo.tercile_probabilities(members, (date(2027, 3, 1), date(2027, 5, 31)), 150, 400, trust=0.5)
    assert shrunk["p_below"] == pytest.approx(0.5 * 0.5 + 0.5 / 3, abs=1e-3)
    assert open_meteo.tercile_probabilities(members, (date(2027, 3, 1), date(2027, 7, 31)), 150, 400, 1.0) is None


def test_kilimostat_loader_converts_units(env, tmp_path):
    from shambasense import db
    from shambasense.ingest import loaders

    path = tmp_path / "kilimostat.csv"
    pd.DataFrame([
        {"County": "Machakos County", "Element": "Area", "Item": "Green Grams", "Value": 1000, "Unit": "Ha", "Year": 2030},
        {"County": "Machakos County", "Element": "Production", "Item": "Green Grams", "Value": 10000, "Unit": "90 Kg Bags", "Year": 2030},
        {"County": "Nairobi", "Element": "Area", "Item": "Maize", "Value": 5, "Unit": "Ha", "Year": 2030},
    ]).to_csv(path, index=False)
    assert loaders.load_kilimostat(path) == 1
    row = db.read_df("SELECT * FROM crop_yield WHERE year = 2030").iloc[0]
    assert row["crop"] == "green_grams" and row["season"] == "annual"
    assert row["yield_t_ha"] == pytest.approx(0.9)       # 10,000 bags x 90 kg / 1,000 ha
    db.replace_rows(db.CropYield, {"year": 2030}, [])


def test_outlook_category_mapping(env, tmp_path):
    from shambasense import db
    from shambasense.ingest import loaders

    path = tmp_path / "outlook.csv"
    pd.DataFrame([{"county": "Meru", "year": 2031, "season": "short_rains", "category": "Above normal"}]).to_csv(path, index=False)
    assert loaders.load_outlooks(path) == 1
    row = db.read_df("SELECT * FROM seasonal_outlook WHERE year = 2031").iloc[0]
    assert row["p_above"] == pytest.approx(0.45) and row["p_below"] == pytest.approx(0.20)


def test_nearest_county(env):
    from shambasense.ingest.loaders import nearest_county

    county, km = nearest_county(-1.52, 37.27)
    assert county == "machakos" and km < 2


def test_harveststat_cleaning_keeps_droughts_and_drops_errors():
    import pandas as pd

    from shambasense.ingest import harveststat

    def rec(product, year, indicator, value, county="Nakuru", season="Annual"):
        return {"admin_1": county, "product": product, "season_name": season, "harvest_year": year,
                "indicator": indicator, "value": value}

    rows = []
    maize = {1990: 2.4, 1991: 2.6, 1992: 2.2, 1993: 2.5, 1994: 2.7, 1995: 2.3, 1996: 0.4,   # 1996: drought, kept
             1997: 2.5, 1998: 30.0}                                                          # 1998: unit slip
    for year, y in maize.items():
        rows.append(rec("Maize", year, "yield", y))
    rows += [rec("Maize", 1975, "yield", 2.0)]                                    # before the weather record
    rows += [rec("Tomato", 2015, "yield", 1.0), rec("Tomato", 2018, "yield", 20.0)]   # placeholder 1.0
    rows += [rec("Beans (mixed)", y, "yield", 0.54) for y in (2001, 2002, 2003, 2004)] + [rec("Beans (mixed)", 2005, "yield", 0.6)]
    rows += [rec("Potato", 2019, "area", 100.0), rec("Potato", 2019, "production", 900.0), rec("Potato", 2019, "yield", 5.0)]
    rows += [rec("Maize", 2019, "yield", 9.9, season="Long")]                   # seasonal rows are not used
    yields, log = harveststat.clean(pd.DataFrame(rows))

    def kept(crop, year):
        return not yields[(yields.crop == crop) & (yields.year == year)].empty

    assert kept("maize", 1996)                         # a bad year stays in
    assert not kept("maize", 1998) and not kept("maize", 1975) and not kept("maize", 2019)
    assert not kept("tomatoes", 2015) and kept("tomatoes", 2018)
    assert kept("beans", 2001) and not any(kept("beans", y) for y in (2002, 2003, 2004)) and kept("beans", 2005)
    assert yields.loc[yields.crop == "potatoes", "yield_t_ha"].iloc[0] == 9.0   # production / area wins
    assert set(log["reason"].str.split().str[0]) >= {"before", "outside", "same"}


def test_wfp_commodities_and_markets():
    from shambasense.ingest import wfp

    assert wfp.crop_for("Maize (white, dry)") == "maize" and wfp.crop_for("Maize flour (white)") is None
    assert wfp.crop_for("Beans (mung)") == "green_grams" and wfp.crop_for("Beans (rosecoco)") == "beans"
    assert wfp.crop_for("Potatoes (Irish, red)") == "potatoes" and wfp.crop_for("Cowpeas") is None
    assert wfp.county_for(-0.30, 36.08) == "nakuru"           # Wakulima market, Nakuru
    assert wfp.county_for(0.52, 35.28) == "trans_nzoia"       # Eldoret, 63 km from Kitale
    assert wfp.county_for(-4.05, 39.67) is None               # Mombasa: a national market
