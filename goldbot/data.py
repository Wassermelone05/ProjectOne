"""Datenquellen für Goldkurse: Yahoo Finance, CSV-Dateien und synthetische Testdaten.

Alle Funktionen liefern einen DataFrame mit DatetimeIndex und den Spalten
open, high, low, close, volume.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ["open", "high", "low", "close", "volume"]


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):  # yfinance liefert (Feld, Ticker)
        df = df.droplevel(-1, axis=1) if df.columns.nlevels > 1 else df
    df = df.rename(columns=lambda c: str(c).strip().lower().replace(" ", "_"))
    if "close" not in df.columns and "adj_close" in df.columns:
        df = df.rename(columns={"adj_close": "close"})
    missing = [c for c in ["open", "high", "low", "close"] if c not in df.columns]
    if missing:
        raise ValueError(f"Fehlende Spalten in den Kursdaten: {missing}")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df = df[COLUMNS].astype(float)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.dropna(subset=["open", "high", "low", "close"])


def load_yahoo(symbol: str = "GC=F", period: str = "5y", interval: str = "1d") -> pd.DataFrame:
    """Lädt Kurse von Yahoo Finance (z. B. GC=F Gold-Futures, GLD ETF)."""
    import yfinance as yf

    df = yf.download(symbol, period=period, interval=interval,
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        raise RuntimeError(
            f"Keine Daten für {symbol!r} von Yahoo erhalten. "
            "Internetverbindung/Symbol prüfen oder --csv verwenden."
        )
    return _normalize(df)


def load_csv(path: str | Path) -> pd.DataFrame:
    """Lädt eine CSV mit Datumsspalte (date/datetime/time) und OHLC(V)-Spalten."""
    df = pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    date_col = next((c for c in ("date", "datetime", "time", "timestamp") if c in df.columns), None)
    if date_col is None:
        raise ValueError("CSV braucht eine Spalte 'date', 'datetime', 'time' oder 'timestamp'")
    df[date_col] = pd.to_datetime(df[date_col], utc=False)
    return _normalize(df.set_index(date_col))


def synthetic(n: int = 1000, start_price: float = 1800.0, seed: int = 42,
              drift: float = 0.0002, vol: float = 0.01) -> pd.DataFrame:
    """Erzeugt einen synthetischen, goldähnlichen Kursverlauf (für Tests/Offline-Demos)."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start_price], close[:-1]]) * (1 + rng.normal(0, vol / 4, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": rng.integers(1_000, 10_000, n).astype(float)}, index=idx)


def load_data(symbol: str, period: str, interval: str, csv: str | None = None,
              demo: bool = False) -> pd.DataFrame:
    if demo:
        return synthetic()
    if csv:
        return load_csv(csv)
    return load_yahoo(symbol, period, interval)
