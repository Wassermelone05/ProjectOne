"""Paper-Trading: holt regelmäßig neue Goldkurse und handelt mit Spielgeld.

Es werden nur abgeschlossene Kerzen verarbeitet, und zwar mit genau derselben
Logik wie im Backtest (engine.py). Der Kontostand wird in einer JSON-Datei
gespeichert, sodass der Bot jederzeit gestoppt und neu gestartet werden kann.
"""
from __future__ import annotations

import logging
import time as _time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .broker import PaperBroker
from .config import Config
from .data import load_data
from .engine import Engine
from .strategy import Strategy

log = logging.getLogger("goldbot.paper")

_INTERVALS = {"m": "min", "h": "h", "d": "D", "wk": "W", "mo": "MS"}


def interval_to_timedelta(interval: str) -> pd.Timedelta:
    num = "".join(ch for ch in interval if ch.isdigit()) or "1"
    unit = interval[len(num):] if interval.startswith(num) else interval.lstrip("0123456789")
    if unit == "wk":
        return pd.Timedelta(weeks=int(num))
    if unit == "mo":
        return pd.Timedelta(days=31 * int(num))
    if unit not in _INTERVALS:
        raise ValueError(f"Unbekanntes Intervall {interval!r}")
    return pd.Timedelta(int(num), unit=_INTERVALS[unit])


def completed_bars(df: pd.DataFrame, interval: str, now: datetime | None = None) -> pd.DataFrame:
    """Entfernt Kerzen, die noch nicht abgeschlossen sind."""
    now = now or datetime.now(timezone.utc)
    now_ts = pd.Timestamp(now)
    if df.index.tz is None:
        now_ts = now_ts.tz_convert("UTC").tz_localize(None) if now_ts.tzinfo else now_ts
    else:
        now_ts = now_ts.tz_convert(df.index.tz)
    bar_end = df.index + interval_to_timedelta(interval)
    return df[bar_end <= now_ts]


class PaperTrader:
    def __init__(self, cfg: Config, strategy: Strategy, csv: str | None = None,
                 demo: bool = False):
        self.cfg, self.strategy, self.csv, self.demo = cfg, strategy, csv, demo
        self.state_path = Path(cfg.paper.state_file)
        self.last_processed: str | None = None
        if self.state_path.exists():
            broker, meta = PaperBroker.load(self.state_path)
            self.last_processed = meta.get("last_processed")
            blocked = meta.get("blocked_signal")
            if meta.get("symbol") not in (None, cfg.symbol):
                log.warning("Status-Datei gehört zu %s, Konfiguration nutzt %s",
                            meta.get("symbol"), cfg.symbol)
            log.info("Paper-Konto geladen: Cash %.2f, Position %.4f",
                     broker.cash, broker.position)
        else:
            broker = PaperBroker(cash=cfg.risk.initial_cash, fee_pct=cfg.costs.fee_pct,
                                 slippage_pct=cfg.costs.slippage_pct)
            blocked = None
            log.info("Neues Paper-Konto mit %.2f angelegt", broker.cash)
        self.engine = Engine(broker, cfg.risk, blocked)

    @property
    def broker(self) -> PaperBroker:
        return self.engine.broker

    def save(self) -> None:
        self.broker.save(self.state_path, {
            "symbol": self.cfg.symbol,
            "interval": self.cfg.interval,
            "strategy": vars(self.cfg.strategy),
            "last_processed": self.last_processed,
            "blocked_signal": self.engine.blocked_signal,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    def step(self, now: datetime | None = None) -> list[str]:
        """Einmal Kurse holen und alle neuen abgeschlossenen Kerzen verarbeiten."""
        df = load_data(self.cfg.symbol, self.cfg.period, self.cfg.interval,
                       csv=self.csv, demo=self.demo)
        df = completed_bars(df, self.cfg.interval, now)
        if len(df) <= self.strategy.warmup:
            log.warning("Noch zu wenige abgeschlossene Kerzen (%d)", len(df))
            return []

        signals = self.strategy.signals(df)
        times = [str(t) for t in df.index]

        if self.last_processed is None:
            # Erster Start: ab der letzten abgeschlossenen Kerze handeln, nicht rückwirkend.
            self.last_processed = times[-1]
            log.info("Start bei Kerze %s, aktuelles Signal %+d", times[-1], signals.iloc[-1])
            self.save()
            return []

        new_idx = [i for i, t in enumerate(times) if pd.Timestamp(t) > pd.Timestamp(self.last_processed)]
        events: list[str] = []
        for i in new_idx:
            row = df.iloc[i]
            for ev in self.engine.on_bar(times[i], row.open, row.high, row.low,
                                         int(signals.iloc[i - 1])):
                msg = f"[{times[i]}] {ev}"
                log.info(msg)
                events.append(msg)
            self.last_processed = times[i]

        last_close = float(df["close"].iloc[-1])
        log.info("Kerze %s | Close %.2f | Signal %+d | Position %.4f | Equity %.2f",
                 times[-1], last_close, signals.iloc[-1], self.broker.position,
                 self.broker.equity(last_close))
        self.save()
        return events

    def run(self) -> None:
        log.info("Paper-Trading gestartet (%s, %s). Abbruch mit Strg+C.",
                 self.cfg.symbol, self.cfg.interval)
        while True:
            try:
                self.step()
            except KeyboardInterrupt:
                raise
            except Exception:  # Netzwerkfehler etc. sollen den Bot nicht beenden
                log.exception("Fehler im Durchlauf – neuer Versuch beim nächsten Intervall")
            _time.sleep(self.cfg.paper.poll_seconds)
