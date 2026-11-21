"""Backtester: spielt die Strategie Kerze für Kerze auf historischen Daten durch
(Handelslogik siehe engine.py) und berechnet Kennzahlen."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .broker import PaperBroker, Trade
from .config import Config
from .engine import Engine
from .strategy import Strategy


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: list[Trade]
    metrics: dict
    signals: pd.Series

    def trades_frame(self) -> pd.DataFrame:
        return pd.DataFrame([t.__dict__ for t in self.trades])


def _periods_per_year(index: pd.DatetimeIndex) -> float:
    if len(index) < 2:
        return 252.0
    span_days = (index[-1] - index[0]).total_seconds() / 86400
    return len(index) / span_days * 365.25 if span_days > 0 else 252.0


def _profit_factor(wins: list[float], losses: list[float]) -> float:
    loss_sum = -sum(losses)
    if loss_sum > 0:
        return sum(wins) / loss_sum
    return float("inf") if wins else 0.0


def compute_metrics(equity: pd.Series, trades: list[Trade], prices: pd.Series,
                    fees_paid: float = 0.0) -> dict:
    start, end = float(equity.iloc[0]), float(equity.iloc[-1])
    rets = equity.pct_change().dropna()
    ppy = _periods_per_year(equity.index)
    years = len(equity) / ppy
    cagr = (end / start) ** (1 / years) - 1 if years > 0 and end > 0 else float("nan")
    sharpe = (rets.mean() / rets.std() * np.sqrt(ppy)) if rets.std() > 0 else 0.0
    drawdown = equity / equity.cummax() - 1
    pnls = [t.pnl for t in trades if t.pnl is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    return {
        "start_equity": start,
        "end_equity": end,
        "total_return_pct": (end / start - 1) * 100,
        "cagr_pct": cagr * 100,
        "max_drawdown_pct": float(drawdown.min()) * 100,
        "sharpe": float(sharpe),
        "trades": len(pnls),
        "win_rate_pct": (len(wins) / len(pnls) * 100) if pnls else 0.0,
        "avg_win": float(np.mean(wins)) if wins else 0.0,
        "avg_loss": float(np.mean(losses)) if losses else 0.0,
        "profit_factor": _profit_factor(wins, losses),
        "fees_paid": fees_paid,
        "buy_hold_return_pct": (float(prices.iloc[-1]) / float(prices.iloc[0]) - 1) * 100,
        "exposure_pct": 0.0,  # wird im Backtest gesetzt
    }


def run_backtest(df: pd.DataFrame, strategy: Strategy, cfg: Config) -> BacktestResult:
    if len(df) <= strategy.warmup + 1:
        raise ValueError(f"Zu wenige Kerzen ({len(df)}) für Warmup von {strategy.warmup}")

    signals = strategy.signals(df)
    broker = PaperBroker(cash=cfg.risk.initial_cash, fee_pct=cfg.costs.fee_pct,
                         slippage_pct=cfg.costs.slippage_pct)
    engine = Engine(broker, cfg.risk)
    equity = np.empty(len(df))
    in_market = 0

    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    sig = signals.to_numpy()
    times = [str(t) for t in df.index]

    for i in range(len(df)):
        engine.on_bar(times[i], o[i], h[i], l[i], int(sig[i - 1]) if i > 0 else None)
        in_market += broker.side != 0
        equity[i] = broker.equity(c[i])

    if broker.side != 0:
        broker.close(c[-1], times[-1], "end")
        equity[-1] = broker.equity(c[-1])

    eq = pd.Series(equity, index=df.index, name="equity")
    metrics = compute_metrics(eq, broker.trades, df["close"], broker.fees_paid)
    metrics["exposure_pct"] = in_market / len(df) * 100
    return BacktestResult(eq, broker.trades, metrics, signals)


def format_report(metrics: dict, title: str = "Backtest") -> str:
    labels = [
        ("start_equity", "Startkapital", "{:,.2f}"),
        ("end_equity", "Endkapital", "{:,.2f}"),
        ("total_return_pct", "Gesamtrendite", "{:+.2f} %"),
        ("buy_hold_return_pct", "Buy & Hold Gold", "{:+.2f} %"),
        ("cagr_pct", "Rendite p. a. (CAGR)", "{:+.2f} %"),
        ("max_drawdown_pct", "Max. Drawdown", "{:.2f} %"),
        ("sharpe", "Sharpe Ratio", "{:.2f}"),
        ("trades", "Anzahl Trades", "{:d}"),
        ("win_rate_pct", "Trefferquote", "{:.1f} %"),
        ("avg_win", "Ø Gewinn-Trade", "{:,.2f}"),
        ("avg_loss", "Ø Verlust-Trade", "{:,.2f}"),
        ("profit_factor", "Profit-Faktor", "{:.2f}"),
        ("exposure_pct", "Zeit im Markt", "{:.1f} %"),
        ("fees_paid", "Gebühren gesamt", "{:,.2f}"),
    ]
    width = max(len(l) for _, l, _ in labels)
    lines = [f"=== {title} ==="]
    for key, label, fmt in labels:
        lines.append(f"{label:<{width}} : {fmt.format(metrics[key])}")
    return "\n".join(lines)
