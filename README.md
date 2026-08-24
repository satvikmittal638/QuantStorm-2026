# QuantStorm 2026 — Divided Oracle Market Maker

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Benchmark: +122.7 PnL/Match](https://img.shields.io/badge/Scoreboard-+122.7%20PnL%2Fmatch-brightgreen.svg)](#benchmark--evaluation-results)
[![Institution: IIT Kanpur](https://img.shields.io/badge/Institution-IIT%20Kanpur-red.svg)](https://www.iitk.ac.in/)

> Autonomous quantitative market maker and algorithmic game theory engine engineered for **QuantStorm 2026 Round 1: "Divided Oracle"**.

---

## Author & Maintainer

- **Satvik Mittal**
- **Indian Institute of Technology Kanpur (IIT Kanpur)**
- **Roll Number:** `240943`
- **GitHub:** [@satvikmittal638](https://github.com/satvikmittal638)
- **Email:** [satvikmittal638@gmail.com](mailto:satvikmittal638@gmail.com)

---

## 1. Executive Summary

In the **Divided Oracle** trading arena, two algorithmic agents trade financial contracts over a hidden asset value $S$, determined by the sum of 40 fair $\pm 1$ coins ($S = \sum_{i=1}^{40} C_i$). Information is asymmetric and revealed sequentially over 5 rounds. Each round features:
1. **Coin Reveals**: 4 private coins revealed per player ($20$ private coins total per player).
2. **First-Price Tactical Energy (TE) Power Auction**: Auctioning one game-altering superpower per round (`FORESIGHT`, `SUBSTITUTE`, `TRICK_ROOM`, `STEALTH_ROCK`, `TRANSFORM`).
3. **6-Turn Interactive Negotiation**: Dynamic continuous two-way quoting ($T_1 \dots T_6$) between Maker and Taker to establish contract settlement prices.
4. **Portfolio Settlement**: Simultaneous terminal settlement with Maker obligation payouts, forced-fill fees, option refunds, and TE salvage yield.

`qs_bot.py` (*Divided Oracle Hybrid Peak Engine*) solves the environment from first principles, integrating **exact combinatorial lattice valuation**, **analytical Bachelier option modeling**, **game-theoretic endgame dominance**, and **real-time Bayesian belief profiling**.

---

## 2. Core Quantitative Edges

```
                                  ┌─────────────────────────────┐
                                  │      Divided Oracle Bot     │
                                  │         (qs_bot.py)         │
                                  └──────────────┬──────────────┘
                                                 │
        ┌────────────────────────┬───────────────┴───────────────┬────────────────────────┐
        ▼                        ▼                               ▼                        ▼
┌───────────────┐        ┌───────────────┐               ┌───────────────┐        ┌───────────────┐
│ Parity Lattice│        │  Bachelier    │               │  Game-Theory  │        │   Bayesian    │
│ Straddle Edge │        │ Option Model  │               │ Turn-6 Endgame│        │ Belief State  │
└───────┬───────┘        └───────┬───────┘               └───────┬───────┘        └───────┬───────┘
        │                        │                               │                        │
        ▼                        ▼                               ▼                        ▼
Exact even parity        Closed-form PnL         Taker dominates via             Physical drift bounds,
binomial lattice         convexity for           (ask, ask) shorting             FORESIGHT forensics &
straddle yield           SUBSTITUTE holdings     at T6 forced-fill               adaptive ride hurdle
```

### 1. Exact Parity-Lattice Straddle & Hypergeometric Pricing
- $S$ is strictly **even-parity** ($S \equiv 0 \pmod 2$). Aligning the opening quote's lower bound to even values doubles the effective coverage density on tight spreads.
- The engine prices maker obligations via a canonical baseline step function `config.straddle_prob(r, w)`. `qs_bot.py` evaluates true hypergeometric probability $p_{\text{true}}$ directly using combinatorics:
  $$p_{\text{true}} = \frac{1}{2^m} \sum_{j \equiv m \pmod 2} \binom{m}{\frac{j+m}{2}}$$
  extracting guaranteed positive expected obligation yield: $\mathbb{E}[\text{EV}] = 3.0 \times (p_{\text{true}} - p_{\text{priced}}) - 0.18 \times (w - \text{floor})$.

### 2. Analytical Bachelier Option Model (`SUBSTITUTE`)
- `SUBSTITUTE` caps contract losses at $-2.0$ ticks.
- Rather than using static heuristic approximations, `qs_bot.py` evaluates the continuous Gaussian integral in closed-form:
  $$\mathbb{E}[\max(X, -2)] = \mu \Phi\left(\frac{\mu+2}{\sigma}\right) - 2 \left(1 - \Phi\left(\frac{\mu+2}{\sigma}\right)\right) + \sigma \phi\left(\frac{\mu+2}{\sigma}\right)$$
  ensuring precision valuation when holding or facing `SUBSTITUTE`.

### 3. Game-Theoretic Turn-6 Forced-Fill Dominance
- The Taker strictly acts on Turn 6 ($T_6$). Width-0 counters are legal.
- At $T_6$, countering `(ask, ask)` converts the Taker into a short position filled at $\text{ask} + \text{shift} - 2.0$, strictly dominating a sell at $\text{bid}$ whenever spread $w > 2$.
- Expected payoff: $\max(v - \text{ask}, \, \text{bid} - v, \, \text{ask} + \text{shift} - v - 2.0) \approx |\text{ask} - v| - 1.0$.

### 4. Bayesian Belief Profiling & Physical Coin Constraints
- **Physical Coin Feasibility**: Enforces $|\text{mid}| \le 4r + 1.0$ and cross-round drift limits $|\text{mid}_{r_2} - \text{mid}_{r_1}| \le 4|r_2 - r_1| + 1.0$ to detect deceptive "liar" archetypes instantly.
- **FORESIGHT Forensics**: Cross-references opponent quote midpoints against leaked true coin samples.
- **Adaptive Ride Hurdle**: Dynamically calibrates early-acceptance thresholds from $0.50$ (high confidence) to $0.85$ (against liars/forcers).

### 5. Tactical Energy (TE) Salvage & Decisive Power Sizing
- Unspent TE yields guaranteed $0.08 \times \Delta\text{TE}$ terminal salvage.
- Evaluates powers (`FORESIGHT`, `SUBSTITUTE`, `STEALTH_ROCK`, `TRICK_ROOM`) against incremental contract edge, bidding dynamically with optimal shading ($0.20 \dots 0.35$).
- Opponents with $\text{TE}_{\text{theirs}} \le 0$ are sniped for exactly $1\text{ TE}$.

---

## 3. Benchmark & Evaluation Results

All benchmarks are run using `lab/scoreboard.py` across **5 independent seeds $\times$ 120 mirrored deals** (1,200 deals per matchup, zero-sum mirrored controls):

```
================================================================================
SCOREBOARD: lab/bot/qs_bot.py (Hybrid Peak Engine)
================================================================================
HONEST PANEL (Standard Competition Benchmark)
--------------------------------------------------------------------------------
  vs naive_ev                     +10.85 +/- 0.43   (+217.0 /match)
  vs rational                     +11.14 +/- 0.28   (+222.8 /match)
  vs adaptive_bidder               +3.57 +/- 0.51   ( +71.4 /match)
  vs CapQuoter                    +10.87 +/- 0.33   (+217.4 /match)
  vs FloorQuoter                   +7.74 +/- 0.45   (+154.8 /match)
  vs FlatBidder                    +4.74 +/- 0.55   ( +94.8 /match)
  vs Sniper                        +6.12 +/- 0.49   (+122.3 /match)
  vs T6Bot                         +4.49 +/- 0.47   ( +89.7 /match)
  vs RideKiller                    +3.82 +/- 0.44   ( +76.4 /match)
  vs HeavyBidder                   +5.39 +/- 0.48   (+107.9 /match)
  vs Aggro                         +3.49 +/- 0.44   ( +69.8 /match)
  vs PennyJumper                   +4.49 +/- 0.47   ( +89.7 /match)
  vs InventoryHoarder              +6.73 +/- 0.39   (+134.7 /match)
  vs OptionPoisoner                +5.27 +/- 0.49   (+105.4 /match)
  vs AsymmetricSkewMaker           +3.34 +/- 0.52   ( +66.8 /match)
--------------------------------------------------------------------------------
  HONEST GROUP MEAN                +6.14 ticks/deal (+122.7 /match)

BOARD RECONSTRUCTIONS (Leaderboard Field Replicas)
--------------------------------------------------------------------------------
  vs o01_raw_bid_sniper            +4.46 +/- 0.44   ( +89.2 /match)
  vs o02_te_opportunity_cost       +4.65 +/- 0.45   ( +93.0 /match)
  vs o03_quote_compressor          +4.27 +/- 0.37   ( +85.3 /match)
  vs o04_counterspy                +3.39 +/- 0.40   ( +67.8 /match)
  vs o05_transform_arbitrageur     +5.30 +/- 0.43   (+105.9 /match)
  vs o06_shift_power_camper        +3.76 +/- 0.49   ( +75.2 /match)
  vs o07_obligation_harvester      +3.39 +/- 0.40   ( +67.8 /match)
  vs o08_forced_fill_engineer      +3.12 +/- 0.51   ( +62.3 /match)
  vs o09_min_counter_squeeze       +5.41 +/- 0.50   (+108.3 /match)
  vs o10_foresight_deflation       +1.94 +/- 0.50   ( +38.8 /match)
--------------------------------------------------------------------------------
  BOARD RECON GROUP MEAN           +3.97 ticks/deal ( +79.4 /match)

Self-Play Symmetry Control:        +0.000000000     (Exact Zero-Sum Invariant OK)
Health / Timing:                   Clean            (Max Call: 4.52 ms < 50.0 ms budget)
================================================================================
```

---

## 4. Repository Structure

```
QuantStorm-2026/
├── README.md                      # Primary project overview & documentation
├── .gitignore                     # Git configuration for Python artifacts
├── docs/
│   └── STRATEGY_DEEP_DIVE.md      # Detailed mathematical derivations & formulas
├── lab/
│   ├── README.md                  # Lab environment & testing harness guide
│   ├── LAB_NOTES.md               # Continuous research log & experiment journal
│   ├── arena.py                   # High-performance parallel match runner
│   ├── scoreboard.py              # 4-panel benchmarking suite
│   ├── board_bots.py              # 10 reconstructed leaderboard archetypes
│   ├── opponents.py               # 15 sparring panel archetypes & baseline bots
│   ├── sweep.py                   # Hyperparameter grid optimizer
│   ├── ablation.py                # Component ablation test harness
│   ├── bot/
│   │   ├── qs_bot.py              # Champion submission strategy
│   │   └── god_bot.py             # Experimental analysis bot
│   └── versions/
│       ├── VERSIONS.md            # Version changelog and regression matrix
│       ├── v1_board_84.83.py      # Historical milestone versions (v1 to v10)
│       └── ...
└── quantstorm-ps/                 # Competition platform engine & rulebook
    ├── engine.py                  # Core simulation engine & deal orchestrator
    ├── game_config.py             # Rule configuration & parameters
    ├── backtester.py              # Match backtester CLI
    ├── sandbox.py                 # Isolated process runner & AST checker
    ├── RULEBOOK.md                # Official competition rulebook
    └── strategies/                # Baseline reference bots (naive_ev, rational, adaptive)
```

---

## 5. Quickstart & Usage

### Prerequisites
- Python 3.10+ (Standard library only: `math`, `random`, `typing`, `collections`, `itertools`, `heapq`, `bisect`, `functools`).

### Running the Full Scoreboard Benchmark
Evaluate `qs_bot.py` across all 38 benchmark opponents:
```bash
python3 lab/scoreboard.py --bot lab/bot/qs_bot.py
```

Fast verification mode (fewer deals for rapid feedback):
```bash
python3 lab/scoreboard.py --bot lab/bot/qs_bot.py --quick
```

### Running Head-to-Head Matches (`arena.py`)
Pit `qs_bot.py` directly against any strategy or reference bot:
```bash
# Duel against the Rational Baseline
python3 lab/arena.py --a lab/bot/qs_bot.py --b quantstorm-ps/strategies/rational.py

# Duel against Shift Power Camper archetype
python3 lab/arena.py --a lab/bot/qs_bot.py --b lab/board_bots.py:o06_shift_power_camper
```

### Running the Platform Backtester
```bash
python3 quantstorm-ps/backtester.py \
  --bot-a lab/bot/qs_bot.py \
  --bot-b quantstorm-ps/strategies/adaptive_bidder.py \
  --deals 100 \
  --verbose
```

---

## 6. Mathematical Documentation

For full mathematical proofs, option model integrals, and game-theoretic matrices, refer to [docs/STRATEGY_DEEP_DIVE.md](docs/STRATEGY_DEEP_DIVE.md).

---

## 7. License

This project is licensed under the [MIT License](LICENSE).
