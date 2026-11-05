"""Accounts, farms, history, reminders and SMS, prices, weather and admin endpoints."""

from __future__ import annotations

from datetime import date, timedelta

import pytest


@pytest.fixture(scope="module")
def client(model):
    from fastapi.testclient import TestClient

    from shambasense.api.main import app

    with TestClient(app) as c:
        yield c


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def farmer(client):
    res = client.post("/api/auth/register", json={"phone": "0712 345 678", "pin": "4826", "name": "Wanjiku",
                                                  "county": "nakuru", "lang": "en"})
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.parametrize("raw, expected", [
    ("0712345678", "+254712345678"), ("+254 712 345 678", "+254712345678"), ("254112345678", "+254112345678"),
    ("712345678", "+254712345678"), ("0812345678", None), ("12345", None), ("", None)])
def test_normalize_phone(env, raw, expected):
    from shambasense.services.auth import normalize_phone

    assert normalize_phone(raw) == expected


def test_pin_hash_roundtrip():
    from shambasense.services.auth import hash_pin, verify_pin

    stored = hash_pin("4826")
    assert verify_pin("4826", stored) and not verify_pin("4827", stored)
    assert "4826" not in stored


def test_register_rules(client, farmer):
    assert farmer["user"]["phone"] == "+254712345678" and farmer["token"]
    dup = client.post("/api/auth/register", json={"phone": "+254712345678", "pin": "4826"})
    assert dup.status_code == 409
    weak = client.post("/api/auth/register", json={"phone": "0722000111", "pin": "1234"})
    assert weak.status_code == 400 and "harder" in weak.json()["detail"]
    bad_phone = client.post("/api/auth/register", json={"phone": "0812345678", "pin": "4826"})
    assert bad_phone.status_code == 400


def test_login_and_lockout(client):
    client.post("/api/auth/register", json={"phone": "0733000222", "pin": "5931"})
    assert client.post("/api/auth/login", json={"phone": "0733000222", "pin": "5931"}).status_code == 200
    for _ in range(5):
        assert client.post("/api/auth/login", json={"phone": "0733000222", "pin": "0001"}).status_code == 401
    locked = client.post("/api/auth/login", json={"phone": "0733000222", "pin": "5931"})
    assert locked.status_code == 429


def test_profile_and_logout(client):
    token = client.post("/api/auth/register", json={"phone": "0744000333", "pin": "8402"}).json()["token"]
    assert client.get("/api/me", headers=_auth(token)).json()["phone_masked"].endswith("333")
    me = client.patch("/api/me", json={"name": "Otieno", "lang": "sw", "county": "meru"}, headers=_auth(token)).json()
    assert me["name"] == "Otieno" and me["lang"] == "sw" and me["county"] == "meru"
    assert client.post("/api/me/pin", json={"old_pin": "8402", "new_pin": "6157"}, headers=_auth(token)).status_code == 200
    client.post("/api/auth/logout", headers=_auth(token))
    assert client.get("/api/me", headers=_auth(token)).status_code == 401
    assert client.get("/api/me").status_code == 401


def test_farms_advice_and_history(client, farmer):
    h = _auth(farmer["token"])
    farm = client.post("/api/farms", json={"name": "Njoro plot", "county": "nakuru", "area_acres": 2}, headers=h)
    assert farm.status_code == 200, farm.text
    farm = farm.json()
    assert farm["county_name"] == "Nakuru" and "long_rains" in farm["seasons"]
    point = client.post("/api/farms", json={"name": "Near Katumani", "lat": -1.55, "lon": 37.25}, headers=h).json()
    assert point["county"] == "machakos"
    assert len(client.get("/api/farms", headers=h).json()) == 2

    advice = client.get(f"/api/farms/{farm['id']}/advice", params={"season": "long_rains", "year": 2027}, headers=h)
    assert advice.status_code == 200 and advice.json()["farm"]["id"] == farm["id"]
    history = client.get("/api/me/history", headers=h).json()
    assert history and history[0]["farm_name"] == "Njoro plot"
    full = client.get(f"/api/me/history/{history[0]['id']}", headers=h).json()
    assert full["season"] == "long_rains"

    other = client.post("/api/auth/register", json={"phone": "0755000444", "pin": "7350"}).json()["token"]
    assert client.get(f"/api/farms/{farm['id']}/advice", headers=_auth(other)).status_code == 404
    assert client.patch(f"/api/farms/{point['id']}", json={"name": "Katumani"}, headers=h).json()["name"] == "Katumani"
    assert client.delete(f"/api/farms/{point['id']}", headers=h).json() == {"deleted": True}


def test_reminders_and_sms(client, farmer, monkeypatch):
    from shambasense import db
    from shambasense.services import reminders

    h = _auth(farmer["token"])
    farm_id = client.get("/api/farms", headers=h).json()[0]["id"]
    rem = client.post(f"/api/farms/{farm_id}/reminders", json={"season": "long_rains", "year": 2027}, headers=h)
    assert rem.status_code == 200, rem.text
    rem = rem.json()
    assert rem["status"] == "scheduled" and rem["send_on"] < "2027-04-01" and len(rem["message"]) <= 300
    assert client.post(f"/api/farms/{farm_id}/reminders", json={"season": "short_rains"},
                       headers=h).status_code in (200, 400)

    # Not configured: logged, not sent, stays scheduled for later.
    counts = reminders.send_due(date(2027, 4, 30))
    assert counts["not_configured"] >= 1
    assert db.read_df("SELECT status FROM sms_log").iloc[-1]["status"] == "not_configured"

    # Configured: Africa's Talking replies with Success.
    class Ok:
        ok, text = True, '{"SMSMessageData":{"Recipients":[{"status":"Success","number":"+254712345678"}]}}'

        def json(self):
            import json
            return json.loads(self.text)

    sent = {}
    monkeypatch.setenv("AT_USERNAME", "sandbox")
    monkeypatch.setenv("AT_API_KEY", "test-key")
    monkeypatch.setenv("SHAMBA_OFFLINE", "0")
    monkeypatch.setattr("shambasense.services.sms.requests.post",
                        lambda url, data, timeout, headers: sent.update(url=url, data=data, headers=headers) or Ok())
    counts = reminders.send_due(date(2027, 4, 30))
    assert counts["sent"] >= 1 and "sandbox" in sent["url"] and sent["headers"]["apiKey"] == "test-key"
    assert sent["data"]["to"] == "+254712345678"
    statuses = [r["status"] for r in client.get("/api/reminders", headers=h).json()]
    assert "sent" in statuses


def test_prices(client):
    s = client.get("/api/prices", params={"crop": "beans", "county": "meru"}).json()
    assert s["points"] and s["latest_kes_kg"] > 0 and s["scope"] == "county"
    summary = client.get("/api/prices/summary", params={"county": "meru"}).json()
    assert {x["crop"] for x in summary} >= {"maize", "beans"}
    assert client.get("/api/prices", params={"crop": "coffee"}).status_code == 400


def test_weather(client, monkeypatch):
    from shambasense.services import weather

    days = [(date(2027, 3, 1) + timedelta(days=i)).isoformat() for i in range(14)]
    rain = [0, 0, 2, 12, 9, 4, 0, 0, 0, 0, 1, 0, 0, 0]
    payload = {"daily": {"time": days, "precipitation_sum": rain, "precipitation_probability_max": [50] * 14,
                         "temperature_2m_max": [27] * 14, "temperature_2m_min": [14] * 14, "weather_code": [61] * 14}}
    monkeypatch.setattr(weather, "get_json", lambda *a, **k: payload)
    w = client.get("/api/weather", params={"county": "machakos"}).json()
    assert len(w["days"]) == 14 and "3 Mar" in w["summary"][1]
    monkeypatch.setattr(weather, "get_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    assert client.get("/api/weather", params={"county": "machakos"}).status_code == 503


def test_admin_access(client, farmer):
    from shambasense.services import auth

    assert client.get("/api/admin/stats").status_code == 401
    assert client.get("/api/admin/stats", headers=_auth(farmer["token"])).status_code == 403
    _, token = auth.register("0766000555", "3907", "Admin", is_admin=True)
    stats = client.get("/api/admin/stats", headers=_auth(token)).json()
    assert stats["users"] >= 3 and stats["recommendations"] >= 1 and len(stats["daily"]) == 31
    assert client.get("/api/admin/stats", headers={"X-Admin-Token": "test-token"}).status_code == 200
    users = client.get("/api/admin/users", headers=_auth(token)).json()
    assert all("•" in u["phone"] for u in users)
    assert client.get("/api/admin/sms", headers=_auth(token)).status_code == 200
    assert client.get("/api/admin/retrain", headers=_auth(token)).json()["running"] is False
    assert client.post("/api/admin/sms/test", json={"phone": "0712345678"}, headers=_auth(token)).json()["status"]


def test_feedback_linked_to_user(client, farmer):
    from shambasense import db

    client.post("/api/feedback", json={"county": "nakuru", "season": "long_rains", "year": 2027, "crop": "potatoes",
                                       "rating": 5}, headers=_auth(farmer["token"]))
    row = db.read_df("SELECT user_id, channel FROM feedback WHERE crop = 'potatoes'").iloc[-1]
    assert row["user_id"] == farmer["user"]["id"] and row["channel"] == "app"
