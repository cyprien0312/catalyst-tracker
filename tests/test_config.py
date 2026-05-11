import pytest
from lib import config


def test_watchlist_hyperscalers_includes_msft():
    assert config.HYPERSCALERS["MSFT"] == "0000789019"


def test_watchlist_neoclouds_includes_crwv():
    assert config.NEOCLOUDS["CRWV"] == "0001769628"


def test_all_ciks_are_10_digit_strings():
    for d in (config.HYPERSCALERS, config.NEOCLOUDS):
        for ticker, cik in d.items():
            assert isinstance(cik, str) and len(cik) == 10 and cik.isdigit(), (ticker, cik)


def test_require_env_returns_value(monkeypatch):
    monkeypatch.setenv("FOO", "bar")
    assert config.require_env("FOO") == "bar"


def test_require_env_raises_when_missing(monkeypatch):
    monkeypatch.delenv("FOO", raising=False)
    with pytest.raises(RuntimeError, match="FOO"):
        config.require_env("FOO")


def test_sec_user_agent_falls_back(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    ua = config.sec_user_agent()
    assert "catalyst-tracker" in ua and "@" in ua
