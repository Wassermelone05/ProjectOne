"""Kommandozeile:  python -m goldbot {backtest,paper,status} [...]"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .backtest import format_report, run_backtest
from .broker import PaperBroker
from .config import load_config
from .data import load_data
from .paper import PaperTrader
from .strategy import build_strategy


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("-c", "--config", default="config.yaml", help="Pfad zur Konfiguration")
    p.add_argument("--symbol", help="Yahoo-Symbol, z. B. GC=F oder GLD")
    p.add_argument("--interval", help="Kerzen-Intervall, z. B. 1d oder 1h")
    p.add_argument("--fast", type=int, help="Periode des schnellen SMA")
    p.add_argument("--slow", type=int, help="Periode des langsamen SMA")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--csv", help="Kursdaten aus CSV statt von Yahoo")
    src.add_argument("--demo", action="store_true", help="Synthetische Daten (offline)")


def _load(args):
    cfg = load_config(args.config)
    if getattr(args, "symbol", None):
        cfg.symbol = args.symbol
    if getattr(args, "interval", None):
        cfg.interval = args.interval
    if getattr(args, "fast", None):
        cfg.strategy.fast = args.fast
    if getattr(args, "slow", None):
        cfg.strategy.slow = args.slow
    cfg.validate()
    return cfg


def cmd_backtest(args) -> int:
    cfg = _load(args)
    if getattr(args, "period", None):
        cfg.period = args.period
    df = load_data(cfg.symbol, cfg.period, cfg.interval, csv=args.csv, demo=args.demo)
    strategy = build_strategy(cfg.strategy)
    res = run_backtest(df, strategy, cfg)
    src = "Demo-Daten" if args.demo else (args.csv or cfg.symbol)
    title = (f"Backtest {src} | {cfg.interval} | SMA {cfg.strategy.fast}/{cfg.strategy.slow} "
             f"| {df.index[0].date()} – {df.index[-1].date()}")
    print(format_report(res.metrics, title))

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        res.trades_frame().to_csv(out / "trades.csv", index=False)
        res.equity.to_csv(out / "equity.csv")
        print(f"\nTrades und Equity-Kurve gespeichert in {out}/")
    if args.show_trades and res.trades:
        print("\nTrades:")
        print(res.trades_frame()[["side", "entry_time", "entry_price", "exit_time",
                                  "exit_price", "pnl", "reason"]].to_string(index=False))
    return 0


def cmd_paper(args) -> int:
    cfg = _load(args)
    trader = PaperTrader(cfg, build_strategy(cfg.strategy), csv=args.csv, demo=args.demo)
    if args.once:
        trader.step()
    else:
        try:
            trader.run()
        except KeyboardInterrupt:
            logging.getLogger("goldbot").info("Beendet.")
    return 0


def cmd_status(args) -> int:
    cfg = load_config(args.config)
    path = Path(cfg.paper.state_file)
    if not path.exists():
        print(f"Noch kein Paper-Konto vorhanden ({path}). Starte mit: python -m goldbot paper")
        return 1
    broker, meta = PaperBroker.load(path)
    print(f"Symbol           : {meta.get('symbol')} ({meta.get('interval')})")
    print(f"Letzte Kerze     : {meta.get('last_processed')}")
    print(f"Cash             : {broker.cash:,.2f}")
    print(f"Position         : {broker.position:.4f}")
    if broker.open_trade:
        t = broker.open_trade
        print(f"Offener Trade    : {t.side} seit {t.entry_time} @ {t.entry_price:.2f}"
              + (f", Stop {broker.stop_price:.2f}" if broker.stop_price else ""))
    closed = [t for t in broker.trades if t.pnl is not None]
    print(f"Geschl. Trades   : {len(closed)} | realisierter PnL {sum(t.pnl for t in closed):+,.2f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="goldbot", description="Gold-TradingBot (SMA-Crossover)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("backtest", help="Strategie auf historischen Daten testen")
    _common(p)
    p.add_argument("--period", help="Zeitraum, z. B. 2y, 5y, 10y, max")
    p.add_argument("--out", help="Ordner für trades.csv / equity.csv")
    p.add_argument("--show-trades", action="store_true", help="Alle Trades ausgeben")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("paper", help="Paper-Trading mit Spielgeld")
    _common(p)
    p.add_argument("--once", action="store_true", help="Nur einen Durchlauf ausführen")
    p.set_defaults(func=cmd_paper)

    p = sub.add_parser("status", help="Stand des Paper-Kontos anzeigen")
    p.add_argument("-c", "--config", default="config.yaml")
    p.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    try:
        return args.func(args)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 2
