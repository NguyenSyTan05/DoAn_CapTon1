import importlib
import sys

import pytest

LONG = "x" * 40


def _reload_config(monkeypatch, secret):
    # Stop load_dotenv from re-supplying a SECRET_KEY from a real .env file.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    if secret is None:
        monkeypatch.delenv("SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("SECRET_KEY", secret)
    sys.modules.pop("config", None)
    return importlib.import_module("config")


@pytest.fixture(autouse=True)
def _restore_config():
    saved = sys.modules.get("config")
    yield
    if saved is not None:
        sys.modules["config"] = saved


@pytest.mark.parametrize("secret", [None, "", "short", "x" * 31])
def test_missing_or_short_secret_key_rejected(monkeypatch, secret):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _reload_config(monkeypatch, secret)


@pytest.mark.parametrize("secret", [LONG, "y" * 32])
def test_long_secret_key_accepted(monkeypatch, secret):
    cfg = _reload_config(monkeypatch, secret)
    assert cfg.Config.SECRET_KEY == secret
