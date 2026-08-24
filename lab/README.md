# Quantitative Research Lab & Evaluation Framework

**Authors:** Satvik Mittal (IIT Kanpur) & Antigravity (Google DeepMind)

The `lab/` directory provides a research harness, benchmarking suite, and opponent simulation panels for evaluating market-making algorithms in the QuantStorm 2026 environment.

---

## Directory Architecture

```
lab/
├── bot/
│   ├── qs_bot.py            # Primary competition entry (Hybrid Peak Engine)
│   └── god_bot.py           # Experimental / analysis bot
├── versions/
│   ├── VERSIONS.md          # Version changelog and performance record
│   ├── v1_board_84.83.py    # Milestone versions v1 through v10
│   └── ...
├── arena.py                 # Core multiprocessing duel engine & match harness
├── scoreboard.py            # Multi-panel benchmarking tool
├── board_bots.py            # Reconstructed leaderboard archetypes (o01 - o10)
├── opponents.py             # Sparring panel archetypes & reference baselines
├── sweep.py                 # Multi-parameter grid search optimizer
├── ablation.py              # Feature-by-feature ablation testing
└── LAB_NOTES.md             # Durable research journal & experiment logs
```

---

## 1. Benchmarking Suite (`scoreboard.py`)

`scoreboard.py` runs a standardized, 4-group evaluation (5 random seeds $\times$ 120 mirrored deals = 1,200 deals per opponent):

1. **Honest Panel (15 archetypes)**: The primary proxy for real competition performance. Includes `naive_ev`, `rational`, `adaptive_bidder`, `CapQuoter`, `FloorQuoter`, `FlatBidder`, `Sniper`, `T6Bot`, `RideKiller`, `HeavyBidder`, `Aggro`, `PennyJumper`, `InventoryHoarder`, `OptionPoisoner`, and `AsymmetricSkewMaker`.
2. **Past Versions (10 models)**: Regression testing against historical checkpoints (`v1` through `v10`).
3. **Board Reconstructions (10 models)**: High-fidelity replicas of the 10 leaderboard opponents (`o01` to `o10`).
4. **Liars Panel (3 adversarial models)**: Stress tests against deceptive quoting strategies (`liar_compress`, `liar_invert`, `liar_zero`).

### Usage:
```bash
# Run full benchmark against all panels
python3 lab/scoreboard.py --bot lab/bot/qs_bot.py

# Fast verification run (fewer deals)
python3 lab/scoreboard.py --bot lab/bot/qs_bot.py --quick
```

---

## 2. Head-to-Head Arena (`arena.py`)

`arena.py` runs parallelized matches between any two bots with role-inversion and hand-mirroring to eliminate coin variance:

```bash
# Test qs_bot against rational baseline
python3 lab/arena.py --a lab/bot/qs_bot.py --b quantstorm-ps/strategies/rational.py

# Test across custom seeds and deal counts
python3 lab/arena.py --a lab/bot/qs_bot.py --b lab/board_bots.py:o06_shift_power_camper --seeds 42,100,2026 --n_deals 200
```

---

## 3. Parameter Sweep & Optimization (`sweep.py`)

Grid search utility for fine-tuning numeric hyperparameters (such as `SHADE`, `RIDE_FRACTION`, and `INVENTORY_SKEW`):

```bash
python3 lab/sweep.py --bot lab/bot/qs_bot.py --param shade --values 0.20,0.25,0.30,0.33,0.35,0.40
```

---

## 4. Feature Ablation Engine (`ablation.py`)

Verifies that each individual component contributes positively to net PnL:

```bash
python3 lab/ablation.py --bot lab/bot/qs_bot.py
```

---

## 5. Sparring Panel Archetypes

| Archetype | Behavior Profile | Counter-Strategy |
|---|---|---|
| `o01_raw_bid_sniper` | Bids 2 TE on all powers; basic quoter | Outbid by +1 on high-value powers; extract spread |
| `o02_te_opportunity_cost` | Bids based on TE salvage conversion rate | Exploit passive auctions; monetize options early |
| `o03_quote_compressor` | Compresses opening quote midpoint by 0.45 | Bayesian liar detection; adjust ride hurdle to 0.85 |
| `o04_counterspy` | Reads opening quote and inverts midpoint | Drift feasibility checks identify bad reads |
| `o05_transform_arbitrageur` | Transforms flat hands into variance | Maintain tight market making |
| `o06_shift_power_camper` | Accumulates shift powers for forced fills | Charge premium; counter $(ask, ask)$ on Turn 6 |
| `o07_obligation_harvester` | Solves width for maker obligation yield | Parity-aligned combinatorial pricing edge |
| `o08_forced_fill_engineer` | Engineers Turn 6 forced fills | Turn-6 dominance rule exploitation |
| `o09_min_counter_squeeze` | Squeezes spread by 2 ticks every turn | Counter tightly around exact expectation |
| `o10_foresight_deflation` | Shrinks midpoint toward zero; denies foresight | Precision forensics recover true underlying distribution |
