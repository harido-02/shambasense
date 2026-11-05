"""Database schema and helpers. SQLite by default; PostgreSQL via DATABASE_URL."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    insert,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Location(Base):
    """A place we hold weather and soil data for: a county reference point or a grid cell."""

    __tablename__ = "location"
    id = Column(String(64), primary_key=True)          # e.g. county:machakos, grid:-1.50_37.50
    kind = Column(String(16), nullable=False)          # county | grid | station
    name = Column(String(128))
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    county_id = Column(String(32))


class ClimateDaily(Base):
    __tablename__ = "climate_daily"
    id = Column(Integer, primary_key=True, autoincrement=True)
    location_id = Column(String(64), nullable=False, index=True)
    date = Column(Date, nullable=False)
    rain_mm = Column(Float)
    tmean_c = Column(Float)
    tmax_c = Column(Float)
    tmin_c = Column(Float)
    source = Column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("location_id", "date", name="uq_climate_loc_date"),)


class SoilProfile(Base):
    """Topsoil (0-30 cm, depth-weighted) properties for a location."""

    __tablename__ = "soil_profile"
    location_id = Column(String(64), primary_key=True)
    ph = Column(Float)
    soc_g_kg = Column(Float)
    nitrogen_g_kg = Column(Float)
    clay_pct = Column(Float)
    sand_pct = Column(Float)
    cec_cmol_kg = Column(Float)
    source = Column(String(64), nullable=False)


class CropYield(Base):
    __tablename__ = "crop_yield"
    id = Column(Integer, primary_key=True, autoincrement=True)
    county_id = Column(String(32), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    season = Column(String(16), nullable=False)        # long_rains | short_rains | annual
    crop = Column(String(32), nullable=False)
    area_ha = Column(Float)
    production_t = Column(Float)
    yield_t_ha = Column(Float, nullable=False)
    source = Column(String(128), nullable=False)
    __table_args__ = (UniqueConstraint("county_id", "year", "season", "crop", name="uq_yield"),)


class MarketPrice(Base):
    __tablename__ = "market_price"
    id = Column(Integer, primary_key=True, autoincrement=True)
    county_id = Column(String(32), index=True)
    market = Column(String(64))
    crop = Column(String(32), nullable=False)
    date = Column(Date, nullable=False)
    wholesale_kes_kg = Column(Float)
    retail_kes_kg = Column(Float)
    source = Column(String(64), nullable=False)


class ProductionCost(Base):
    __tablename__ = "production_cost"
    id = Column(Integer, primary_key=True, autoincrement=True)
    county_id = Column(String(32), index=True)
    crop = Column(String(32), nullable=False)
    cost_kes_ha = Column(Float, nullable=False)
    source = Column(String(128), nullable=False)


class SeasonalOutlook(Base):
    __tablename__ = "seasonal_outlook"
    id = Column(Integer, primary_key=True, autoincrement=True)
    county_id = Column(String(32), nullable=False)
    year = Column(Integer, nullable=False)
    season = Column(String(16), nullable=False)
    p_below = Column(Float, nullable=False)
    p_normal = Column(Float, nullable=False)
    p_above = Column(Float, nullable=False)
    source = Column(String(128), nullable=False)
    issued_on = Column(Date)
    __table_args__ = (UniqueConstraint("county_id", "year", "season", name="uq_outlook"),)


class RecommendationLog(Base):
    __tablename__ = "recommendation_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), default=_now)
    channel = Column(String(16))                        # web | ussd | api | cli
    user_hash = Column(String(64))                      # hashed phone number, never the number
    lat = Column(Float)
    lon = Column(Float)
    county_id = Column(String(32))
    season = Column(String(16))
    year = Column(Integer)
    top_crop = Column(String(32))
    response_json = Column(Text)
    user_id = Column(Integer, index=True)
    farm_id = Column(Integer)


class Feedback(Base):
    """What a farmer planted and how it went: the loop for improving the model."""

    __tablename__ = "feedback"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), default=_now)
    channel = Column(String(16))
    user_hash = Column(String(64))
    county_id = Column(String(32))
    season = Column(String(16))
    year = Column(Integer)
    crop = Column(String(32))
    followed_advice = Column(Integer)                  # 1 yes, 0 no
    rating = Column(Integer)                            # 1-5
    yield_bags_acre = Column(Float)
    notes = Column(Text)
    user_id = Column(Integer, index=True)
    farm_id = Column(Integer)


# ------------------------------------------------------------------ accounts and app features

class User(Base):
    """A farmer, extension officer or administrator. Signs in with phone number and PIN."""

    __tablename__ = "app_user"
    id = Column(Integer, primary_key=True, autoincrement=True)
    phone = Column(String(16), unique=True, nullable=False)    # E.164, e.g. +254712345678
    name = Column(String(80))
    county_id = Column(String(32))
    lang = Column(String(2), default="en")
    pin_hash = Column(String(200), nullable=False)
    is_admin = Column(Integer, default=0)
    sms_opt_in = Column(Integer, default=0)
    failed_logins = Column(Integer, default=0)
    locked_until = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=_now)
    last_login_at = Column(DateTime(timezone=True))


class AuthSession(Base):
    __tablename__ = "auth_session"
    token_hash = Column(String(64), primary_key=True)          # sha256 of the bearer token
    user_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class Farm(Base):
    __tablename__ = "farm"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    name = Column(String(80), nullable=False)
    lat = Column(Float)
    lon = Column(Float)
    county_id = Column(String(32), nullable=False)
    area_acres = Column(Float)
    created_at = Column(DateTime(timezone=True), default=_now)


class Reminder(Base):
    """An SMS planting reminder scheduled for a farm and season."""

    __tablename__ = "reminder"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    farm_id = Column(Integer, nullable=False)
    season = Column(String(16), nullable=False)
    year = Column(Integer, nullable=False)
    send_on = Column(Date, nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String(16), default="scheduled")       # scheduled | sent | failed | cancelled
    sent_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("farm_id", "season", "year", name="uq_reminder"),)


class SmsLog(Base):
    __tablename__ = "sms_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), default=_now)
    to_phone = Column(String(16), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String(32), nullable=False)             # sent | failed | not_configured
    provider_response = Column(Text)


_engine: Engine | None = None
_engine_url: str | None = None
_Session: sessionmaker | None = None


def engine() -> Engine:
    global _engine, _engine_url, _Session
    url = config.database_url()
    if _engine is None or url != _engine_url:
        kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
        _engine = create_engine(url, future=True, **kwargs)
        _engine_url = url
        _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def session() -> Session:
    engine()
    assert _Session is not None
    return _Session()


def init_db() -> None:
    Base.metadata.create_all(engine())
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Lightweight migration: add nullable columns that newer versions introduced."""
    from sqlalchemy import inspect, text

    insp = inspect(engine())
    with engine().begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing and col.nullable:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} '
                                      f'{col.type.compile(dialect=engine().dialect)}'))


def reset_db() -> None:
    Base.metadata.drop_all(engine())
    Base.metadata.create_all(engine())


def replace_rows(model, filters: dict, records: list[dict]) -> int:
    """Delete rows matching `filters`, then bulk-insert `records`. Returns rows inserted."""
    with session() as s, s.begin():
        stmt = delete(model)
        for key, value in filters.items():
            stmt = stmt.where(getattr(model, key) == value)
        s.execute(stmt)
        if records:
            s.execute(insert(model), records)
    return len(records)


def upsert_location(loc_id: str, kind: str, name: str, lat: float, lon: float, county_id: str | None) -> None:
    with session() as s, s.begin():
        s.merge(Location(id=loc_id, kind=kind, name=name, lat=lat, lon=lon, county_id=county_id))


def read_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    from sqlalchemy import text

    with engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def climate_df(location_id: str) -> pd.DataFrame:
    df = read_df(
        "SELECT date, rain_mm, tmean_c, tmax_c, tmin_c FROM climate_daily WHERE location_id = :loc ORDER BY date",
        {"loc": location_id},
    )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def soil_dict(location_id: str) -> dict | None:
    df = read_df("SELECT * FROM soil_profile WHERE location_id = :loc", {"loc": location_id})
    if df.empty:
        return None
    return df.iloc[0].to_dict()
