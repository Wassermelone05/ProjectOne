"""Gemeinsame Handelslogik pro Kerze – identisch für Backtest und Paper-Trading.

Ablauf pro Kerze:
  1. Stop-Loss / Take-Profit anhand von Open/High/Low der Kerze prüfen.
  2. Signal der Vorkerze zum Eröffnungskurs ausführen  -> kein Look-Ahead.
Nach einem Stop wird erst wieder eingestiegen, wenn sich das Signal ändert.
"""
from __future__ import annotations

from .broker import PaperBroker
from .config import RiskConfig


class Engine:
    def __init__(self, broker: PaperBroker, risk: RiskConfig,
                 blocked_signal: int | None = None):
        self.broker = broker
        self.risk = risk
        self.blocked_signal = blocked_signal

    def on_bar(self, time: str, open_: float, high: float, low: float,
               prev_signal: int | None) -> list[str]:
        """Verarbeitet eine abgeschlossene Kerze. Gibt Log-Ereignisse zurück."""
        b, events = self.broker, []

        t = b.check_exits(open_, high, low, time)
        if t is not None:
            self.blocked_signal = 1 if t.side == "long" else -1
            events.append(f"{t.reason}: {t.side} geschlossen @ {t.exit_price:.2f} (PnL {t.pnl:+.2f})")

        if prev_signal is None:
            return events
        target = int(prev_signal)
        if self.blocked_signal is not None and target != self.blocked_signal:
            self.blocked_signal = None
        if self.blocked_signal is not None or target == b.side:
            return events

        if b.side != 0:
            t = b.close(open_, time, "signal")
            events.append(f"signal: {t.side} geschlossen @ {t.exit_price:.2f} (PnL {t.pnl:+.2f})")
        if target != 0:
            t = b.open(target, open_, time, self.risk.risk_fraction,
                       self.risk.stop_loss_pct, self.risk.take_profit_pct)
            if t is not None:
                stop = f", Stop {b.stop_price:.2f}" if b.stop_price else ""
                events.append(f"open: {t.side} {t.qty:.4f} @ {t.entry_price:.2f}{stop}")
                # Der Stop kann bereits in der Einstiegskerze greifen
                x = b.check_exits(open_, high, low, time)
                if x is not None:
                    self.blocked_signal = target
                    events.append(f"{x.reason}: {x.side} geschlossen @ {x.exit_price:.2f} (PnL {x.pnl:+.2f})")
        return events
