"""Lädt die Konfiguration aus config.yaml in typisierte Dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class StrategyConfig:
    name: str = "sma_crossover"
    fast: int = 20
    slow: int = 50
    allow_short: bool = False


@dataclass
class RiskConfig:
    initial_cash: float = 10_000.0
    risk_fraction: float = 0.95
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.0


@dataclass
class CostConfig:
    fee_pct: float = 0.0005
    slippage_pct: float = 0.0002


@dataclass
class PaperConfig:
    state_file: str = "state/paper_state.json"
    poll_seconds: int = 3600


@dataclass
class Config:
    symbol: str = "GC=F"
    interval: str = "1d"
    period: str = "5y"
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    costs: CostConfig = field(default_factory=CostConfig)
    paper: PaperConfig = field(default_factory=PaperConfig)

    def validate(self) -> None:
        s, r = self.strategy, self.risk
        if s.fast <= 0 or s.slow <= 0:
            raise ValueError("SMA-Perioden müssen positiv sein")
        if s.fast >= s.slow:
            raise ValueError(f"fast ({s.fast}) muss kleiner als slow ({s.slow}) sein")
        if not 0 < r.risk_fraction <= 1:
            raise ValueError("risk_fraction muss zwischen 0 und 1 liegen")
        if r.stop_loss_pct < 0 or r.take_profit_pct < 0:
            raise ValueError("stop_loss_pct / take_profit_pct dürfen nicht negativ sein")


def load_config(path: str | Path = "config.yaml") -> Config:
    path = Path(path)
    raw: dict = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg = Config(
        symbol=raw.get("symbol", Config.symbol),
        interval=raw.get("interval", Config.interval),
        period=raw.get("period", Config.period),
        strategy=StrategyConfig(**raw.get("strategy", {})),
        risk=RiskConfig(**raw.get("risk", {})),
        costs=CostConfig(**raw.get("costs", {})),
        paper=PaperConfig(**raw.get("paper", {})),
    )
    cfg.validate()
    return cfg
