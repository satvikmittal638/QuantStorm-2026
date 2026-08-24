# QuantStorm 2026 — Divided Oracle Algorithmic Market Maker

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Benchmark: +122.7 PnL/Match](https://img.shields.io/badge/Scoreboard-+122.7%20PnL%2Fmatch-brightgreen.svg)](#3-benchmark--evaluation-results)

> Autonomous quantitative market maker and algorithmic game theory engine engineered for **QuantStorm 2026 Round 1: "Divided Oracle"**.

---

## Table of Contents
- [1. Executive Summary & Problem Formulation](#1-executive-summary--problem-formulation)
- [2. Strategy Architecture & Core Quantitative Edges](#2-strategy-architecture--core-quantitative-edges)
  - [Edge 1: Exact Parity-Lattice Straddle & Hypergeometric Pricing](#1-exact-parity-lattice-straddle--hypergeometric-pricing)
  - [Edge 2: Analytical Bachelier Option Model (SUBSTITUTE)](#2-analytical-bachelier-option-model-substitute)
  - [Edge 3: Game-Theoretic Turn-6 Forced-Fill Dominance](#3-game-theoretic-turn-6-forced-fill-dominance)
  - [Edge 4: Bayesian Belief Profiling & Physical Forensics](#4-bayesian-belief-profiling--physical-forensics)
  - [Edge 5: Adaptive Information-Driven Ride Hurdle](#5-adaptive-information-driven-ride-hurdle)
  - [Edge 6: Tactical Energy (TE) Valuation & Auction Sizing](#6-tactical-energy-te-valuation--auction-sizing)
- [3. Benchmark & Evaluation Results](#3-benchmark--evaluation-results)
- [4. Repository Structure & Tour](#4-repository-structure--tour)
- [5. Quickstart & How to Run](#5-quickstart--how-to-run)
- [6. Mathematical Deep Dive](#6-mathematical-deep-dive)
- [7. Authors & Contributors](#7-authors--contributors)
- [8. License](#8-license)

---

## 1. Executive Summary & Problem Formulation

In the **Divided Oracle** trading arena, two algorithmic agents trade financial contracts over a hidden asset value $S$, determined by the sum of 40 fair $\pm 1$ coins ($S = \sum_{i=1}^{40} C_i$). Information is asymmetric and revealed sequentially over 5 rounds.

### 1.1 Deal Lifecycle
```
Round 1..5 Sequence:
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ 1. Coin Reveal  │ ──► │ 2. Power Auction│ ──► │ 3. Negotiation  │ ──► │ 4. S-Settlement │
│ (4 coins/player)│     │ (Blind 1st-price│     │ (≤6 turns quotes│     │ (End of Round 5)│
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
```

1. **Coin Reveals**: 4 private coins revealed per player ($20$ private coins total per player across 5 rounds).
2. **First-Price Tactical Energy (TE) Power Auction**: Players bid from their 100 TE endowment on game-altering superpowers (`FORESIGHT`, `SUBSTITUTE`, `TRICK_ROOM`, `STEALTH_ROCK`, `TRANSFORM`). Unspent TE converts to terminal salvage at $0.08\text{ ticks per TE}$.
3. **6-Turn Interactive Negotiation**: Continuous two-way quote-and-counter ($T_1 \dots T_6$) between Maker and Taker to establish contract settlement prices.
4. **Portfolio Settlement**: Simultaneous terminal settlement with Maker obligation payouts, forced-fill fees ($2.0$), option refunds, and TE salvage yield.

`qs_bot.py` (*Divided Oracle Hybrid Peak Engine*) solves this sequential game from first principles, integrating **exact combinatorial lattice valuation**, **analytical Bachelier option modeling**, **game-theoretic endgame dominance**, and **real-time Bayesian belief profiling**.

---

## 2. Strategy Architecture & Core Quantitative Edges

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
- **Even Parity Property**: $S = \sum_{i=1}^{40} C_i \equiv 0 \pmod 2$. $S$ is strictly even.
- **Straddle Yield Extraction**: Maker obligation rewards the Maker when $S \in [\text{lo}, \text{lo} + w]$:
  $$\text{Payout} = 3.0 \times (1 - p_{\text{priced}}) \quad \text{vs} \quad \text{Miss Penalty} = -3.0 \times p_{\text{priced}}$$
- By forcing the lower bound $\text{lo}$ to be **even**, an opening width $w=2$ covers **two reachable points** (e.g. $\{0, 2\}$) rather than one, doubling straddle probability for free.
- Computes exact combinatorial probability $p_{\text{true}}$ via binomial coefficients:
  $$p_{\text{true}}(m, \text{lo}, w, v) = \frac{1}{2^m} \sum_{\substack{j = \text{lo} - v \\ (j - m) \equiv 0 \pmod 2}}^{\text{lo} - v + w} \binom{m}{\frac{j + m}{2}}$$
  and solves $(w^*, \text{lo}^*)$ to maximize net expected yield against the width tax.

### 2. Analytical Bachelier Option Model (`SUBSTITUTE`)
- `SUBSTITUTE` introduces asymmetric capped losses at $-2.0\text{ ticks}$.
- `qs_bot.py` models contract return $X \sim \mathcal{N}(\mu, \sigma^2)$ and evaluates the Gaussian payoff integral in closed form:
  $$\mathbb{E}[\max(X, -2)] = \mu \Phi\left(\frac{\mu+2}{\sigma}\right) - 2 \left(1 - \Phi\left(\frac{\mu+2}{\sigma}\right)\right) + \sigma \phi\left(\frac{\mu+2}{\sigma}\right)$$
- Against an opponent holding `SUBSTITUTE`: $\mathbb{E}[\min(X, +2)] = -\mathbb{E}[\max(-X, -2)]$.

### 3. Game-Theoretic Turn-6 Forced-Fill Dominance
- The Taker strictly acts last at Turn 6 ($T_6$). Width-0 counters are legal.
- At $T_6$, countering `(ask, ask)` converts the Taker into a short position filled at $\text{ask} + \text{shift} - 2.0$, strictly dominating a sell at $\text{bid}$ whenever spread $w > 2$.
- Effective Turn-6 Payoff: $\max(v - \text{ask}, \, \text{bid} - v, \, \text{ask} + \text{shift} - v - 2.0) \approx |\text{ask} - v| - 1.0$.

### 4. Bayesian Belief Profiling & Physical Forensics
- **Physical Coin Feasibility Bounds**: Enforces $|\text{mid}| \le 4r + 1.0$ and cross-round drift $|\text{mid}_{r_2} - \text{mid}_{r_1}| \le 4|r_2 - r_1| + 1.0$ to penalize deceptive opponents ($p_{\text{honest}} \leftarrow p_{\text{honest}} \times 0.1$).
- **Ground-Truth FORESIGHT Forensics**: Leaked coin samples $f_{\text{sum}}$ are cross-referenced against quote midpoints ($|\text{mid} - f_{\text{sum}}| > 2.5 \implies p_{\text{honest}} \leftarrow 0.0$).
- **Signal Fusion**: Weighted combination of FORESIGHT and historical honest quotes using inverse-variance Gaussian weighting.

### 5. Adaptive Information-Driven Ride Hurdle
- Replaces static thresholds with dynamic spread fractions: $\text{Hurdle} = \text{ride} \times (\text{ask} - \text{bid})$.
- Calibrates from $0.50$ (high confidence) to $0.85$ (against liars and shift campers) to preserve Turn-6 optionality.

### 6. Tactical Energy (TE) Valuation & Auction Sizing
- Unspent TE earns guaranteed terminal salvage ($0.08\text{ ticks per TE}$).
- Each power is priced against incremental PnL advantage:
  - `FORESIGHT`: $V(r) \approx 0.75\sqrt{\min(16, 4r)}$
  - `SUBSTITUTE`: $V(r) = 0.5(r + 1)$
  - `STEALTH_ROCK`: $V(r) = 0.5(6 - r)$
  - `TRICK_ROOM`: $V(r) = 0.6 / r$
- Bids are shaded dynamically ($0.20 \dots 0.35$); broke opponents ($\text{TE}_{\text{theirs}} \le 0$) are sniped for $1\text{ TE}$.

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

## 4. Repository Structure & Tour

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

## 5. Quickstart & How to Run

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
Duel `qs_bot.py` against any strategy:
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

## 6. Mathematical Deep Dive

For full derivations, option model integrals, and game-theoretic matrices, see [docs/STRATEGY_DEEP_DIVE.md](docs/STRATEGY_DEEP_DIVE.md).

---

## 7. Authors & Contributors

- **Satvik Mittal** — *Lead Developer & Quantitative Strategy Design*
  - Indian Institute of Technology Kanpur (IIT Kanpur), Roll No: `240943`
  - GitHub: [@satvikmittal638](https://github.com/satvikmittal638)
  - Email: [satvikmittal638@gmail.com](mailto:satvikmittal638@gmail.com)

- **Antigravity** — *AI Pair Programmer & Quantitative Architecture Assistant*
  - Advanced Agentic AI Assistant, Google DeepMind

---

## 8. License

This project is licensed under the [MIT License](LICENSE).
