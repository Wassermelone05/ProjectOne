"""Simulierter Broker (Paper-Trading). Wird vom Backtester und vom Paper-Trader genutzt,
damit beide exakt dieselbe Ausführungslogik (Gebühren, Slippage, Stops) verwenden.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Trade:
    side: str            # "long" oder "short"
    qty: float
    entry_time: str
    entry_price: float
    exit_time: str | None = None
    exit_price: float | None = None
    pnl: float | None = None
    reason: str | None = None   # "signal", "stop_loss", "take_profit", "end"


@dataclass
class PaperBroker:
    cash: float
    fee_pct: float = 0.0
    slippage_pct: float = 0.0
    position: float = 0.0              # >0 long, <0 short (Unzen/Kontrakte, gebrochen erlaubt)
    entry_price: float = 0.0
    stop_price: float | None = None
    take_profit_price: float | None = None
    open_trade: Trade | None = None
    trades: list[Trade] = field(default_factory=list)
    fees_paid: float = 0.0

    # ------------------------------------------------------------------ Abfragen
    @property
    def side(self) -> int:
        return int(self.position > 0) - int(self.position < 0)

    def equity(self, price: float) -> float:
        return self.cash + self.position * price

    # ------------------------------------------------------------------ Ausführung
    def _fill(self, qty: float, price: float, apply_slippage: bool = True) -> float:
        """Führt eine Order über qty (signiert) aus und gibt den Ausführungspreis zurück."""
        qty, price = float(qty), float(price)
        slip = self.slippage_pct if apply_slippage else 0.0
        fill = price * (1 + slip) if qty > 0 else price * (1 - slip)
        fee = abs(qty) * fill * self.fee_pct
        self.cash -= qty * fill + fee
        self.fees_paid += fee
        self.position += qty
        if abs(self.position) < 1e-12:
            self.position = 0.0
        return fill

    def open(self, direction: int, price: float, time: str, risk_fraction: float,
             stop_loss_pct: float = 0.0, take_profit_pct: float = 0.0) -> Trade | None:
        if direction == 0 or self.position != 0:
            return None
        price = float(price)
        budget = self.equity(price) * risk_fraction
        cost_per_unit = price * (1 + self.slippage_pct) * (1 + self.fee_pct)
        qty = float(budget / cost_per_unit)
        if qty <= 0:
            return None
        fill = self._fill(direction * qty, price)
        self.entry_price = fill
        self.stop_price = fill * (1 - direction * stop_loss_pct) if stop_loss_pct > 0 else None
        self.take_profit_price = (fill * (1 + direction * take_profit_pct)
                                  if take_profit_pct > 0 else None)
        self.open_trade = Trade("long" if direction > 0 else "short", qty, time, fill)
        return self.open_trade

    def close(self, price: float, time: str, reason: str = "signal",
              apply_slippage: bool = True) -> Trade | None:
        if self.position == 0 or self.open_trade is None:
            return None
        qty = self.position
        cash_before = self.cash
        fill = self._fill(-qty, price, apply_slippage)
        t = self.open_trade
        entry_fee = abs(qty) * t.entry_price * self.fee_pct
        t.exit_time, t.exit_price, t.reason = time, fill, reason
        # PnL inkl. Ein- und Ausstiegsgebühren
        t.pnl = (self.cash - cash_before) - qty * t.entry_price - entry_fee
        self.trades.append(t)
        self.open_trade, self.entry_price = None, 0.0
        self.stop_price = self.take_profit_price = None
        return t

    def check_exits(self, open_: float, high: float, low: float, time: str) -> Trade | None:
        """Prüft Stop-Loss/Take-Profit innerhalb einer Kerze. Bei Kurslücken wird
        zum Eröffnungskurs ausgeführt. Ist beides möglich, gilt konservativ der Stop."""
        if self.position == 0:
            return None
        long = self.position > 0
        if self.stop_price is not None:
            hit = low <= self.stop_price if long else high >= self.stop_price
            if hit:
                gap = open_ <= self.stop_price if long else open_ >= self.stop_price
                return self.close(open_ if gap else self.stop_price, time, "stop_loss")
        if self.take_profit_price is not None:
            hit = high >= self.take_profit_price if long else low <= self.take_profit_price
            if hit:
                gap = open_ >= self.take_profit_price if long else open_ <= self.take_profit_price
                return self.close(open_ if gap else self.take_profit_price, time,
                                  "take_profit", apply_slippage=gap)
        return None

    # ------------------------------------------------------------------ Persistenz
    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PaperBroker":
        d = dict(d)
        d["trades"] = [Trade(**t) for t in d.get("trades", [])]
        if d.get("open_trade"):
            d["open_trade"] = Trade(**d["open_trade"])
        return cls(**d)

    def save(self, path: str | Path, extra: dict | None = None) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"broker": self.to_dict(), **(extra or {})}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: str | Path) -> tuple["PaperBroker", dict]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        broker = cls.from_dict(payload.pop("broker"))
        return broker, payload
