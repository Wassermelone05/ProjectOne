"""Handelsstrategien. Eine Strategie liefert pro Kerze eine Zielposition:
+1 = long, 0 = flat, -1 = short. Das Signal einer Kerze basiert nur auf Daten
bis einschließlich ihres Schlusskurses und wird erst zur nächsten Kerze ausgeführt.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from .config import StrategyConfig


class Strategy(ABC):
    name: str = "base"

    @property
    @abstractmethod
    def warmup(self) -> int:
        """Anzahl Kerzen, bevor die Strategie gültige Signale liefert."""

    @abstractmethod
    def signals(self, df: pd.DataFrame) -> pd.Series:
        """Zielposition (-1/0/+1) für jede Kerze."""


class SmaCrossover(Strategy):
    """Long, solange der schnelle SMA über dem langsamen liegt (optional short darunter)."""

    name = "sma_crossover"

    def __init__(self, fast: int = 20, slow: int = 50, allow_short: bool = False):
        if fast >= slow:
            raise ValueError("fast muss kleiner als slow sein")
        self.fast, self.slow, self.allow_short = fast, slow, allow_short

    @property
    def warmup(self) -> int:
        return self.slow

    def indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        out["sma_fast"] = df["close"].rolling(self.fast).mean()
        out["sma_slow"] = df["close"].rolling(self.slow).mean()
        return out

    def signals(self, df: pd.DataFrame) -> pd.Series:
        ind = self.indicators(df)
        below = -1 if self.allow_short else 0
        sig = pd.Series(0, index=df.index, dtype=int)
        sig[ind["sma_fast"] > ind["sma_slow"]] = 1
        sig[ind["sma_fast"] < ind["sma_slow"]] = below
        sig[ind["sma_slow"].isna()] = 0
        return sig


STRATEGIES = {SmaCrossover.name: SmaCrossover}


def build_strategy(cfg: StrategyConfig) -> Strategy:
    try:
        cls = STRATEGIES[cfg.name]
    except KeyError:
        raise ValueError(f"Unbekannte Strategie {cfg.name!r}. Verfügbar: {list(STRATEGIES)}")
    return cls(fast=cfg.fast, slow=cfg.slow, allow_short=cfg.allow_short)
