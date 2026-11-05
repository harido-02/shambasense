"""Shared fixtures: an isolated database loaded with SYNTHETIC data and a quickly trained model."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("shamba")
    # TEST_DATABASE_URL runs the suite against another database, e.g. PostgreSQL.
    os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL") or f"sqlite:///{root / 'test.db'}"
    os.environ["SHAMBA_DATA_DIR"] = str(root / "data")
    os.environ["SHAMBA_MODEL_DIR"] = str(root / "models")
    os.environ["SHAMBA_OFFLINE"] = "1"
    os.environ["ADMIN_TOKEN"] = "test-token"
    os.environ["SHAMBA_REMINDERS"] = "0"
    for key in ("AT_USERNAME", "AT_API_KEY"):
        os.environ.pop(key, None)
    from shambasense import config, db

    config.clear_caches()
    if os.getenv("TEST_DATABASE_URL"):
        db.reset_db()
    db.init_db()
    return root


@pytest.fixture(scope="session")
def sample_db(env):
    from shambasense.ingest import synthetic

    synthetic.generate(seed=11)
    return env


@pytest.fixture(scope="session")
def table(sample_db):
    from shambasense.features.dataset import build_training_table

    return build_training_table()


@pytest.fixture(scope="session")
def model(table):
    """Fit without cross-validation (fast), then mark as synthetic like the real pipeline would."""
    from shambasense.models.yield_model import YieldModel

    m = YieldModel(sorted(table["crop"].unique())).fit(table)
    m.meta = {"version": "test", "trained_at": "2026-11-05T00:00:00+00:00", "data_quality": "synthetic"}
    m.save()
    return m
