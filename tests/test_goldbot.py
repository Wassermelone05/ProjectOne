from datetime import datetime

import numpy as np
import pandas as pd
import pytest

import goldbot.paper as paper_mod
from goldbot.backtest import run_backtest
from goldbot.broker import PaperBroker
from goldbot.config import Config, StrategyConfig, load_config
from goldbot.data import load_csv, synthetic
from goldbot.paper import PaperTrader, completed_bars
from goldbot.strategy import SmaCrossover


def make_cfg(**risk) -> Config:
    cfg = Config(strategy=StrategyConfig(fast=5, slow=20))
    cfg.costs.fee_pct = 0.001
    cfg.costs.slippage_pct = 0.0005
    for k, v in risk.items():
        setattr(cfg.risk, k, v)
    return cfg


def frame(close: np.ndarray) -> pd.DataFrame:
    idx = pd.bdate_range("2022-01-03", periods=len(close))
    return pd.DataFrame({"open": close, "high": close * 1.002, "low": close * 0.998,
                         "close": close, "volume": 1.0}, index=idx)


# --------------------------------------------------------------------- Strategie
def test_signals_have_no_lookahead():
    df = synthetic(300, seed=1)
    strat = SmaCrossover(10, 30)
    base = strat.signals(df)
    changed = df.copy()
    changed.iloc[200:] *= 3  # Zukunft drastisch verändern
    assert (strat.signals(changed).iloc[:200] == base.iloc[:200]).all()


def test_sma_crossover_goes_long_in_uptrend_and_flat_in_downtrend():
    close = np.concatenate([np.linspace(100, 200, 60), np.linspace(200, 100, 60)])
    sig = SmaCrossover(5, 20).signals(frame(close))
    assert sig.iloc[:19].eq(0).all()          # Warmup (slow-1 Kerzen ohne gültigen SMA)
    assert sig.iloc[55] == 1
    assert sig.iloc[-1] == 0


def test_short_signals_when_allowed():
    close = np.linspace(200, 100, 60)
    assert SmaCrossover(5, 20, allow_short=True).signals(frame(close)).iloc[-1] == -1


# --------------------------------------------------------------------- Broker
@pytest.mark.parametrize("direction", [1, -1])
def test_broker_pnl_matches_equity_change(direction):
    b = PaperBroker(cash=10_000, fee_pct=0.001, slippage_pct=0.0005)
    b.open(direction, 2000.0, "t0", risk_fraction=0.9)
    t = b.close(2100.0, "t1")
    assert b.position == 0
    assert b.cash - 10_000 == pytest.approx(t.pnl)
    assert (t.pnl > 0) == (direction == 1)


def test_stop_loss_fills_at_stop_or_gap_open():
    b = PaperBroker(cash=10_000)
    b.open(1, 100.0, "t0", 1.0, stop_loss_pct=0.05)
    assert b.stop_price == pytest.approx(95.0)
    t = b.check_exits(99, 100, 94, "t1")
    assert t.reason == "stop_loss" and t.exit_price == pytest.approx(95.0)

    b.open(1, 100.0, "t2", 1.0, stop_loss_pct=0.05)
    t = b.check_exits(90, 92, 89, "t3")      # Kurslücke unter den Stop
    assert t.exit_price == pytest.approx(90.0)


def test_take_profit():
    b = PaperBroker(cash=10_000)
    b.open(-1, 100.0, "t0", 1.0, take_profit_pct=0.1)
    t = b.check_exits(95, 96, 89, "t1")
    assert t.reason == "take_profit" and t.exit_price == pytest.approx(90.0)
    assert t.pnl > 0


def test_broker_roundtrip_serialization(tmp_path):
    b = PaperBroker(cash=5_000, fee_pct=0.001)
    b.open(1, 100.0, "t0", 0.5, stop_loss_pct=0.02)
    b.save(tmp_path / "s.json", {"last_processed": "x"})
    b2, meta = PaperBroker.load(tmp_path / "s.json")
    assert b2 == b and meta["last_processed"] == "x"


# --------------------------------------------------------------------- Backtest
def test_backtest_final_equity_equals_sum_of_pnl():
    cfg = make_cfg(stop_loss_pct=0.03)
    res = run_backtest(synthetic(800, seed=7), SmaCrossover(5, 20), cfg)
    assert res.metrics["trades"] > 0
    assert res.equity.iloc[-1] == pytest.approx(cfg.risk.initial_cash + sum(t.pnl for t in res.trades))


def test_backtest_profits_from_clear_trend():
    close = np.concatenate([np.full(30, 100.0), np.linspace(100, 200, 100)])
    res = run_backtest(frame(close), SmaCrossover(5, 20), make_cfg(stop_loss_pct=0.0))
    assert res.metrics["total_return_pct"] > 50
    assert res.trades[0].entry_price > 100  # Einstieg erst nach dem Signal


def test_no_reentry_after_stop_until_signal_changes():
    up = np.linspace(100, 150, 60)
    down = np.linspace(150, 110, 40)
    up2 = np.linspace(110, 170, 60)
    df = frame(np.concatenate([up, down, up2]))
    crash = df.index[40]                   # Kerze mit langem Docht nach unten
    df.loc[crash, "low"] = df.loc[crash, "close"] * 0.8

    res = run_backtest(df, SmaCrossover(5, 20), make_cfg(stop_loss_pct=0.05))
    reasons = [t.reason for t in res.trades]
    assert reasons[0] == "stop_loss"
    assert pd.Timestamp(res.trades[0].exit_time) == crash
    # Kein Wiedereinstieg im laufenden Aufwärtstrend; erst nach neuem Kreuzen (up2)
    assert pd.Timestamp(res.trades[1].entry_time) > df.index[100]


# --------------------------------------------------------------------- Paper
def test_completed_bars_drops_forming_bar():
    df = frame(np.linspace(100, 110, 5))
    now = datetime(2022, 1, 7, 12, 0)  # 5. Kerze (07.01.) läuft noch
    assert len(completed_bars(df, "1d", now)) == 4


def test_paper_trading_matches_backtest(tmp_path, monkeypatch):
    """Kerze für Kerze gefüttert (inkl. Neustart je Kerze) muss Paper-Trading
    exakt dieselben Trades erzeugen wie der Backtest."""
    df = synthetic(400, seed=3)
    cfg = make_cfg(stop_loss_pct=0.04)
    cfg.paper.state_file = str(tmp_path / "state.json")
    strat = SmaCrossover(5, 20)
    start = strat.warmup + 1                 # vorher ist der Backtest garantiert flat

    current = {"k": start}
    monkeypatch.setattr(paper_mod, "load_data", lambda *a, **k: df.iloc[:current["k"]])
    far_future = datetime(2100, 1, 1)
    for k in range(start, len(df) + 1):
        current["k"] = k
        PaperTrader(cfg, strat).step(far_future)   # jedes Mal neu laden = Neustart-sicher

    paper, _ = PaperBroker.load(cfg.paper.state_file)
    bt = run_backtest(df, strat, cfg)
    key = lambda t: (t.side, t.entry_time, round(t.entry_price, 8), t.exit_time,
                     None if t.exit_price is None else round(t.exit_price, 8))
    expected = [key(t) for t in bt.trades]
    got = [key(t) for t in paper.trades]
    if paper.open_trade:                      # Backtest schließt am Ende zwangsweise
        assert bt.trades[-1].reason == "end"
        expected = expected[:-1]
        assert paper.open_trade.entry_time == bt.trades[-1].entry_time
    assert len(got) > 3
    assert got == expected


# --------------------------------------------------------------------- Config/Daten
def test_config_validation(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("strategy:\n  fast: 50\n  slow: 20\n")
    with pytest.raises(ValueError):
        load_config(p)


def test_load_csv(tmp_path):
    p = tmp_path / "gold.csv"
    p.write_text("Date,Open,High,Low,Close\n2024-01-02,2060,2075,2050,2070\n2024-01-03,2070,2072,2030,2040\n")
    df = load_csv(p)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df["close"].iloc[-1] == 2040
