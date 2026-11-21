# Gold-TradingBot

Ein TradingBot in Python für den Goldmarkt mit einer **SMA-Crossover-Strategie**.
Er kann Strategien an historischen Daten testen (**Backtest**) und mit Spielgeld
live mitlaufen (**Paper-Trading**). Echte Orders werden **nicht** gesendet.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Benutzung

```bash
# Backtest mit Gold-Futures (GC=F) der letzten 5 Jahre laut config.yaml
python -m goldbot backtest

# Andere Parameter / anderes Symbol / alle Trades anzeigen
python -m goldbot backtest --fast 10 --slow 30 --period 10y --show-trades
python -m goldbot backtest --symbol GLD            # Gold-ETF statt Futures
python -m goldbot backtest --out results           # trades.csv + equity.csv speichern

# Offline mit eigenen Daten oder synthetischen Demodaten
python -m goldbot backtest --csv meine_golddaten.csv
python -m goldbot backtest --demo

# Paper-Trading (läuft dauerhaft, prüft alle poll_seconds auf neue Kerzen)
python -m goldbot paper
python -m goldbot paper --once                     # ein Durchlauf, z. B. per Cron
python -m goldbot status                           # Stand des Paper-Kontos
```

Gold-Symbole bei Yahoo Finance: `GC=F` (COMEX-Futures), `GLD` / `IAU` (ETFs).
Eine CSV braucht die Spalten `date, open, high, low, close` (optional `volume`).

## Strategie

* **Long**, solange der schnelle SMA (Standard 20) über dem langsamen SMA (50) liegt,
  sonst flat. Mit `allow_short: true` wird stattdessen short gegangen.
* Das Signal einer Kerze wird erst zum **Eröffnungskurs der nächsten Kerze** ausgeführt,
  damit kein Blick in die Zukunft entsteht.
* **Stop-Loss** / **Take-Profit** in Prozent werden innerhalb jeder Kerze über High/Low
  geprüft. Bei Kurslücken wird zum Eröffnungskurs ausgeführt. Nach einem Stop wird
  erst nach einem Signalwechsel wieder eingestiegen.
* Gebühren und Slippage werden bei jedem Trade abgezogen.

Alle Einstellungen stehen in [`config.yaml`](config.yaml).

## Paper-Trading

* Es werden nur **abgeschlossene** Kerzen verarbeitet, und zwar mit derselben Engine
  wie im Backtest. Ein Test stellt sicher, dass beide identische Trades liefern.
* Der Kontostand liegt in `state/paper_state.json`. Der Bot kann jederzeit gestoppt
  und neu gestartet werden. Zum Zurücksetzen die Datei löschen.
* Beim ersten Start handelt der Bot ab der aktuellen Kerze, nicht rückwirkend.

## Projektstruktur

```
goldbot/
  config.py     Konfiguration (config.yaml -> Dataclasses)
  data.py       Kursdaten: Yahoo Finance, CSV, synthetisch
  strategy.py   Strategien (SMA-Crossover), leicht erweiterbar
  broker.py     Simulierter Broker: Orders, Gebühren, Slippage, Stops, Speichern
  engine.py     Handelslogik pro Kerze (gemeinsam für Backtest & Paper)
  backtest.py   Backtest und Kennzahlen (CAGR, Drawdown, Sharpe, …)
  paper.py      Paper-Trading-Schleife
  cli.py        Kommandozeile
tests/          pytest-Tests (python -m pytest)
```

## Eigene Strategie hinzufügen

Eine Klasse von `Strategy` ableiten, `warmup` und `signals(df)` implementieren
(Rückgabe pro Kerze: `1` long, `0` flat, `-1` short) und in `STRATEGIES` in
`goldbot/strategy.py` eintragen.

## Hinweis

Nur zu Lern- und Testzwecken. Backtest-Ergebnisse garantieren keine zukünftigen
Gewinne. Keine Anlageberatung.
