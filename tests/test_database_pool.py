import importlib

import pytest

from app.core import config, database

POOL_ENV = ("DB_POOL_SIZE", "DB_MAX_OVERFLOW", "DB_POOL_TIMEOUT", "DB_POOL_RECYCLE")


@pytest.fixture
def reload_config(monkeypatch):
    def reload(**env):
        for name in POOL_ENV:
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        return importlib.reload(config)

    yield reload
    for name in POOL_ENV:
        monkeypatch.delenv(name, raising=False)
    importlib.reload(config)


def test_pool_settings_default_values(reload_config):
    settings = reload_config()

    assert settings.DB_POOL_SIZE == 20
    assert settings.DB_MAX_OVERFLOW == 20
    assert settings.DB_POOL_TIMEOUT == 30
    assert settings.DB_POOL_RECYCLE == 3600


def test_pool_settings_come_from_environment(reload_config):
    settings = reload_config(DB_POOL_SIZE="12", DB_MAX_OVERFLOW="3", DB_POOL_TIMEOUT="7", DB_POOL_RECYCLE="600")

    assert settings.DB_POOL_SIZE == 12
    assert settings.DB_MAX_OVERFLOW == 3
    assert settings.DB_POOL_TIMEOUT == 7
    assert settings.DB_POOL_RECYCLE == 600


@pytest.mark.parametrize(
    "size, overflow, setting",
    [("0", "0", "DB_POOL_SIZE"), ("0", "20", "DB_POOL_SIZE"),
     ("-1", "20", "DB_POOL_SIZE"), ("1", "-1", "DB_MAX_OVERFLOW")],
)
def test_pool_settings_reject_unbounded_or_nonpositive_capacity(reload_config, size, overflow, setting):
    with pytest.raises(ValueError, match=setting):
        reload_config(DB_POOL_SIZE=size, DB_MAX_OVERFLOW=overflow)


def test_pool_settings_accept_a_finite_pool_without_overflow(reload_config):
    settings = reload_config(DB_POOL_SIZE="1", DB_MAX_OVERFLOW="0")

    assert settings.DB_POOL_SIZE == 1
    assert settings.DB_MAX_OVERFLOW == 0


def test_engine_uses_pool_settings(monkeypatch):
    monkeypatch.setattr(database, "DB_POOL_SIZE", 12)
    monkeypatch.setattr(database, "DB_MAX_OVERFLOW", 3)
    monkeypatch.setattr(database, "DB_POOL_TIMEOUT", 7)
    monkeypatch.setattr(database, "DB_POOL_RECYCLE", 600)

    engine = database._build_engine()
    try:
        assert engine.pool.size() == 12
        assert engine.pool._max_overflow == 3
        assert engine.pool._timeout == 7
        assert engine.pool._recycle == 600
        assert engine.pool._pre_ping is True
    finally:
        engine.dispose()
