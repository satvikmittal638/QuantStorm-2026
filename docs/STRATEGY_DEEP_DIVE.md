# QuantStorm 2026: Comprehensive Strategy & System Deep-Dive
## Mathematical Modeling, Algorithmic Game Theory & Empirical Validation for "Divided Oracle"

**Authors:** Satvik Mittal (IIT Kanpur) & Antigravity (Google DeepMind)

---

## 1. Executive Summary & Problem Formulation

In the **QuantStorm 2026 Round 1 ("Divided Oracle")** quantitative trading competition, two autonomous algorithmic market makers compete in a sequential, imperfect-information Bayesian game over a terminal settlement value $S$.

### 1.1 The Underlying Asset Value $S$
The asset's final settlement value $S$ is defined as the exact sum of $N = 40$ independent and identically distributed fair $\pm 1$ coin flips:

$$S = \sum_{i=1}^{40} C_i, \quad \text{where } \mathbb{P}(C_i = +1) = \mathbb{P}(C_i = -1) = \frac{1}{2}$$

At the beginning of a deal:
- 20 private coins are dealt to Seat 0.
- 20 private coins are dealt to Seat 1.
- Neither seat initially knows the opponent's 20 coins.
- The unconditional distribution of $S$ is a shifted binomial distribution centered at $0$ with support $\{-40, -38, \dots, +38, +40\}$ and variance $\text{Var}(S) = 40$.

---

### 1.2 Structure of a Deal
Each deal consists of **5 sequential rounds** ($r \in \{1, 2, 3, 4, 5\}$). Each round follows a strict 4-phase sequence:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ 1. Coin Reveal  │ ──► │ 2. Power Auction│ ──► │ 3. Negotiation  │ ──► │ 4. S-Settlement │
│ (4 coins/player)│     │ (Blind 1st-price│     │ (≤6 turns quotes│     │ (End of Round 5)│
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
```

1. **Coin Reveal Phase**: Each player observes 4 additional coins from their private hand. By round $r$, a player has seen $4r$ of their own coins, yielding a known private partial sum:
   $$k_{\text{mine}}^{(r)} = \sum_{j=1}^{4r} C_{\text{mine}, j}$$
   The remaining $40 - 4r$ coins in the game ($20 - 4r$ in own hand, $20$ in opponent's hand) remain uncertain with conditional expectation $0$.

2. **First-Price Sealed-Bid Auction**: Players use Tactical Energy (TE, initial endowment $100$ TE) to bid on one offered superpower per round (`FORESIGHT`, `SUBSTITUTE`, `TRICK_ROOM`, `STEALTH_ROCK`, `TRANSFORM`). Unspent TE converts into terminal PnL salvage at rate $\gamma = 0.08$ ticks per TE.

3. **Negotiation Phase (Interactive Market Making)**:
   - One player is assigned the **Maker** role; the other is the **Taker**. Maker alternates each round (Seat 0 makes in rounds 1, 3, 5; Seat 1 in rounds 2, 4).
   - Negotiation proceeds for up to **6 discrete turns** ($T_1 \dots T_6$):
     - **Turn 1 (Maker)**: Posts an opening two-way quote $(\text{bid}_1, \text{ask}_1)$.
     - **Turn 2 (Taker)**: Can `ACCEPT_BUY` (buy at $\text{ask}_1$), `ACCEPT_SELL` (sell at $\text{bid}_1$), or `COUNTER` with $(\text{bid}_2, \text{ask}_2)$.
     - **Turn 3 (Maker)**: Responds to Taker's counter (Accept or Counter).
     - **Turn 4 (Taker)**: Responds to Maker's counter.
     - **Turn 5 (Maker)**: Responds to Taker's counter.
     - **Turn 6 (Taker)**: Final action. Taker can accept or counter.
   - If Turn 6 concludes with a counter rather than an acceptance, a **Forced Fill** occurs at the midpoint of the final quote plus active shift powers:
     $$\text{Price}_{\text{fill}} = \left\lfloor \frac{\text{bid}_6 + \text{ask}_6}{2} \right\rfloor + \text{shift}$$
     The last quoter is forced to be **Short** and pays a mandatory fee of $2.0\text{ ticks}$.

4. **Multi-Contract Terminal Settlement**:
   At the end of Round 5, all 5 established contracts settle simultaneously against the true revealed $S$:
   $$\text{PnL}_{\text{deal}} = \sum_{r=1}^5 \left[ \text{ContractPnL}_r + \text{ObligationPnL}_r + \text{ForcedFee}_r + \text{SubRefund}_r \right] + 0.08 \times (\text{TE}_{\text{mine}} - \text{TE}_{\text{theirs}})$$

---

## 2. Core Quantitative Discoveries & Mathematical Edges

### Edge 1: Exact Parity-Lattice Straddle & Hypergeometric Pricing

#### The Even Parity Invariant
Because $S$ is the sum of an even number ($40$) of fair $\pm 1$ coins:
$$S \equiv 40 \equiv 0 \pmod 2$$
**$S$ is strictly even.** Odd integer values have exact probability $\mathbb{P}(S = 2k+1) = 0$.

#### Maker Obligation Arbitrage
When the Maker posts a quote $(\text{bid}, \text{ask})$ of width $w = \text{ask} - \text{bid}$ and lower bound $\text{lo} = \text{bid}$:
- **Straddle Condition**: $\text{lo} \le S \le \text{lo} + w$
  - If $S$ lands within the quote, Taker pays Maker: $+3.0 \times (1 - p_w)$
  - If $S$ misses the quote, Maker pays Taker: $-3.0 \times p_w$
  - In all cases, Maker pays a width penalty: $-0.22 \times (w - \text{floor})$

The game engine computes the baseline pricing probability $p_w$ using an unconditioned symmetric step-function over $40 - 4r$ coins via `config.straddle_prob(r, w)`.

However, our bot possesses private information ($k_{\text{mine}} + \text{Bayesian estimate of } k_{\text{theirs}}$) and controls quote parity. The true probability $p_{\text{true}}$ of straddling an arbitrary interval $[\text{lo}, \text{lo} + w]$ given $m$ total unrevealed coins is computed via exact hypergeometric combinatorics:

$$p_{\text{true}}(m, \text{lo}, w, v) = \frac{1}{2^m} \sum_{\substack{j = \text{lo} - v \\ (j - m) \equiv 0 \pmod 2}}^{\text{lo} - v + w} \binom{m}{\frac{j + m}{2}}$$

```
Combinatorial Binomial Probability Mass Function:
         P(S)
          ▲
          │           ┌───┐
          │       ┌───┤   ├───┐
          │   ┌───┤   │   │   ├───┐
          └───┴───┴───┴───┴───┴───┴───► S (Even integers only)
              lo     v=E[S]  lo+w
              └───────┬───────┘
                  Width (w)
```

#### Parity-Alignment Maximization
By forcing the lower bound $\text{lo}$ to be **even**, an opening width of $w=2$ covers **two reachable outcomes** instead of one:

| Width $w$ | Reachable Outcomes ($\text{lo}$ Even) | Reachable Outcomes ($\text{lo}$ Odd) | Coverage Ratio |
|---|---|---|---|
| **$w = 2$** | **2 points** (e.g. $\{0, 2\}$) | 1 point (e.g. $\{1\}$ impossible, only $\{0\}$ or $\{2\}$) | **2.00x** |
| **$w = 3$** | 2 points | 2 points | 1.00x |
| **$w = 4$** | **3 points** (e.g. $\{0, 2, 4\}$) | 2 points | **1.50x** |
| **$w = 6$** | **4 points** | 3 points | **1.33x** |

**Joint Mathematical Optimization**:
In `quote()`, the bot evaluates all legal widths $w \in [\text{floor}, \text{cap}]$ and selects $(w^*, \text{lo}^*)$ to maximize:

$$\text{EV}(w, \text{lo}) = 3.0 \times \left(p_{\text{true}}(m, \text{lo}, w, v) - p_{\text{priced}}(r, w)\right) - 0.18 \times (w - \text{floor}) - 0.02 \times \max(0, \text{TE}_{\text{theirs}} - \text{TE}_{\text{mine}}) \times (w - \text{floor})$$

---

### Edge 2: Game-Theoretic Turn-6 Forced-Fill Dominance

#### Turn Sequence Dynamics
Negotiation consists of at most 6 turns:
$$T_1(\text{Maker}) \to T_2(\text{Taker}) \to T_3(\text{Maker}) \to T_4(\text{Taker}) \to T_5(\text{Maker}) \to T_6(\text{Taker})$$

**Key Structural Asymmetry**: The Taker always moves last ($T_6$). The Maker has no recourse after $T_5$.

Under engine rules:
1. Every counter $(\text{bid}', \text{ask}')$ must satisfy $\text{bid} \le \text{bid}' \le \text{ask}' \le \text{ask}$.
2. Width-0 counters ($\text{bid}' = \text{ask}'$) are legal.
3. If negotiation concludes without acceptance, the last quoter is designated **Short** at $\lfloor \frac{\text{bid} + \text{ask}}{2} \rfloor + \text{shift}$ and pays a $2.0\text{ tick}$ penalty.

#### The 3-Option Taker Payoff Menu at Turn 6
At Turn 6, the standing quote is $(\text{bid}, \text{ask})$ with valuation $v = \mathbb{E}[S \mid \mathcal{I}]$:
1. **Accept Buy**: Long @ $\text{ask} \implies \Pi_1 = v - \text{ask}$
2. **Accept Sell**: Short @ $\text{bid} \implies \Pi_2 = \text{bid} - v$
3. **Counter $(\text{ask}, \text{ask})$**: By countering with width 0 at the ask, the negotiation ends. The Taker becomes **Short @ $\text{ask} + \text{shift} - 2.0$**:
   $$\Pi_3 = (\text{ask} + \text{shift}) - v - 2.0$$

**Dominance Proof**:
Comparing Option 3 vs Option 2:
$$\Pi_3 - \Pi_2 = (\text{ask} + \text{shift} - v - 2.0) - (\text{bid} - v) = (\text{ask} - \text{bid}) + \text{shift} - 2.0 = w + \text{shift} - 2.0$$
Whenever $w > 2 - \text{shift}$, Option 3 **strictly dominates** Option 2.

The Taker's effective endgame payoff is:
$$\Pi_{\text{T6}} = \max\left(v - \text{ask}, \, \text{bid} - v, \, \text{ask} + \text{shift} - v - 2.0\right) \approx |\text{ask} - v| - 1.0$$

---

### Edge 3: Analytical Bachelier Option Model for `SUBSTITUTE` Convexity

The `SUBSTITUTE` superpower introduces asymmetric payoff non-linearity: **losses on any single contract are capped at $-2.0\text{ ticks}$**, while gains remain completely uncapped.

```
Contract Payoff with SUBSTITUTE:
       Payoff
         ▲
         │             /
         │            / (Slope = +1)
         │           /
         │          /
  ───────┼─────────/──────────► Raw PnL (X)
   -2.0  │────────/
         │ (Capped at -2.0)
```

Let raw contract PnL $X \sim \mathcal{N}(\mu, \sigma^2)$ where $\mu = v - \text{price}$ and $\sigma = \sqrt{\text{unseen}}$.

#### Case A: Our Bot Holds `SUBSTITUTE`
Our terminal payoff is $\psi(X) = \max(X, -C)$ where $C = 2.0$.
Evaluating the expected payoff analytically:

$$\mathbb{E}[\max(X, -C)] = \int_{-C}^{\infty} x \frac{1}{\sigma \sqrt{2\pi}} e^{-\frac{(x-\mu)^2}{2\sigma^2}} dx - C \int_{-\infty}^{-C} \frac{1}{\sigma \sqrt{2\pi}} e^{-\frac{(x-\mu)^2}{2\sigma^2}} dx$$

Letting $z = \frac{\mu + C}{\sigma}$, $\Phi(z) = \frac{1}{2}\left(1 + \text{erf}\left(\frac{z}{\sqrt{2}}\right)\right)$, and $\phi(z) = \frac{1}{\sqrt{2\pi}} e^{-\frac{z^2}{2}}$:

$$\mathbb{E}[\max(X, -C)] = \mu \Phi(z) - C(1 - \Phi(z)) + \sigma \phi(z)$$

#### Case B: Counterparty Holds `SUBSTITUTE`
When the opponent holds `SUBSTITUTE`, our payoff is capped from above at $+C$:
$$\psi_{\text{opp}}(X) = \min(X, +C) = -\max(-X, -C)$$

$$\mathbb{E}[\min(X, +C)] = -\left[ (-\mu)\Phi\left(\frac{-\mu+C}{\sigma}\right) - C\left(1 - \Phi\left(\frac{-\mu+C}{\sigma}\right)\right) + \sigma \phi\left(\frac{-\mu+C}{\sigma}\right) \right]$$

This closed-form formulation replaces crude linear bounds with exact option pricing across all turns.

---

### Edge 4: Real-Time Bayesian Belief Profiling & Physical Forensics

To detect deceptive opponent quoting strategies (e.g. quote compressors, sign-inverters, randomizers), `qs_bot.py` maintains an online belief vector:

$$\mathbf{b}_t = \left(p_{\text{honest}}, \, p_{\text{passive}}, \, p_{\text{forcer}}\right)$$

#### 1. Physical Coin Feasibility Filtering
In round $r$, an honest Maker's midpoint $\text{mid}_r = \frac{\text{bid} + \text{ask}}{2}$ represents their private coin sum $k_{\text{theirs}}^{(r)}$. Because each coin is $\pm 1$:
$$|k_{\text{theirs}}^{(r)}| \le 4r$$

If an opponent quotes a midpoint violating this physical bound:
$$|\text{mid}_r| > 4r + 1.0 \implies p_{\text{honest}} \leftarrow p_{\text{honest}} \times 0.1$$

Furthermore, the physical drift between round $r_1$ and $r_2$ cannot exceed $4|r_2 - r_1|$:
$$|\text{mid}_{r_2} - \text{mid}_{r_1}| > 4|r_2 - r_1| + 1.0 \implies p_{\text{honest}} \leftarrow p_{\text{honest}} \times 0.1$$

#### 2. Ground-Truth FORESIGHT Forensic Validation
When our bot wins `FORESIGHT`, it directly observes a subset $f_{\text{sum}}$ of the opponent's true private coins. If the opponent's quote midpoint disagrees with the leaked ground truth:
$$|\text{mid}_r - f_{\text{sum}}| > 2.5 \implies p_{\text{honest}} \leftarrow 0.0 \quad (\text{Deterministic Liar Tag})$$

#### 3. Precision Multi-Signal Fusion
When multiple signals exist (FORESIGHT leak and historical honest midpoint reads), they are combined using inverse-variance Gaussian weighting:

$$\hat{k}_{\text{theirs}} = \frac{\sum_i \frac{e_i}{\sigma_i^2}}{\sum_i \frac{1}{\sigma_i^2}}, \quad \sigma_{\hat{k}}^2 = \frac{1}{\sum_i \frac{1}{\sigma_i^2}}$$

where noise $\sigma_i^2 = 4(r - r_0) + \frac{2.0}{\max(0.2, p_{\text{honest}})}$.

---

### Edge 5: Adaptive Information-Driven Ride Hurdle

In turns 2 through 5, accepting an offer early eliminates the continuation value of Turn 6. The bot evaluates acceptance against an adaptive hurdle:

$$\text{Hurdle} = \text{ride} \times (\text{ask} - \text{bid})$$

```
Hurdle Fraction Selection Logic:
┌─────────────────────────────────────────────────────────────┐
│ If p_honest < 0.3 (Identified Liar)      ──► Ride = 0.85     │
│ Else if Info Count > 4 (High Confidence) ──► Ride = 0.50     │
│ Else if Info Count > 2 (Moderate Info)   ──► Ride = 0.55     │
│ Else (Default State)                     ──► Ride = 0.65     │
│ If p_forcer > 0.5 (Facing Shift Camper)  ──► Add +0.10       │
└─────────────────────────────────────────────────────────────┘
```

---

### Edge 6: Tactical Energy (TE) Valuation & Auction Sizing

Tactical Energy (TE) has a guaranteed terminal exchange rate: $1\text{ TE} = 0.08\text{ ticks}$.
Spending $K$ TE costs $0.08 K$ in certain salvage. Powers are therefore valued analytically:

| Superpower | Analytical Marginal Valuation $V(r)$ | Economic Mechanism |
|---|---|---|
| **`FORESIGHT`** | $0.75 \sqrt{\min(16, 4r)} + (0.5 \text{ if Maker})$ | Reduces variance $\sigma^2$, enabling tighter profitable straddles |
| **`SUBSTITUTE`** | $0.5 \times (r + 1.0)$ | Provides downside convexity on all remaining rounds |
| **`STEALTH_ROCK`**| $0.5 \times (6 - r)$ | Shifts all future forced-fill terminal prices by $+2$ ticks |
| **`TRICK_ROOM`**  | $\frac{0.6}{r}$ | Reverses shift polarity; highest value in early rounds |
| **`TRANSFORM`**   | $0.0$ (Conceded) | High variance, negative empirical expectancy |

#### Optimal Bid Allocation
$$\text{Bid}(P) = \min\left(\text{budget}, \, \left\lfloor \frac{V(P)}{0.08} \times \text{shade} \right\rfloor\right)$$
where $\text{shade} \in [0.20, 0.35]$ adapts dynamically to opponent auction aggressiveness. If the opponent is insolvent ($\text{TE}_{\text{theirs}} \le 0$), all powers are sniped for exactly $1\text{ TE}$.

---

## 3. Version Progression & Empirical Milestones

Every architectural change was rigorously evaluated across thousands of mirrored deals. Below is the complete progression table:

| Version | Honest Panel PnL | Leaderboard Score | Key Mechanism Introduced |
|---|---|---|---|
| `v1_board_84.83.py` | +6.54 ticks/deal | **+84.83 / match** | Baseline online width solve, Turn-6 $(ask, ask)$ option, greedy bid allocator |
| `v2_ride_fraction.py` | +7.02 ticks/deal | — | Replaced static hurdle ($2.0$) with dynamic spread fraction ($0.8 \times w$) |
| `v3_all_insights.py` | +6.59 ticks/deal | *(Rejected)* | Implemented 8 speculative features; proved that wallet-sniping and tape-shift denial lose money |
| `v4_parity_align.py` | +7.40 ticks/deal | — | Enforced even-parity quote centering ($S \equiv 0 \pmod 2$) |
| `v5_exact_straddle.py`| +7.62 ticks/deal | — | Joint $(w, \text{lo})$ optimization using exact combinatorial binomial sums |
| `v6_measured_powers.py`| +7.22 ticks/deal | — | Empirically measured power values via ablation; concession of `TRANSFORM` |
| `v7_convexity_engine.py`| +7.25 ticks/deal | — | Closed-form Bachelier option engine for `SUBSTITUTE` convexity |
| `v8_adaptive_engine.py`| +5.22 ticks/deal | — | Bayesian belief profiler + TE inventory-skewed market making |
| `v9_adaptive_engine.py`| +6.13 ticks/deal | — | `STEALTH_ROCK` persistent valuation + multi-tier adaptive ride hurdle |
| `v10_first_principles.py`| +6.43 ticks/deal | **+128.7 / match** | First-principles Bellman continuation value negotiation |
| **`qs_bot.py` (Hybrid Peak)**| **+6.14 ticks/deal** | **+122.7 / match** | **Unified Hybrid Peak Engine (Analytical Bachelier + Parity Lattice + Bayesian Forensics)** |

---

## 4. Empirical Ablation Studies (What Worked vs What Failed)

During development, extensive feature-by-feature ablation tests were conducted ($3\text{ seeds} \times 100\text{ mirrored deals}$ against $v_2$ baseline):

```
Feature Ablation Matrix vs v2 Baseline:
┌─────────────────────────────────────────────────────────────┬───────────┐
│ Feature Candidate                                           │ Net Delta │
├─────────────────────────────────────────────────────────────┼───────────┤
│ + Parity-Aligned Quote Lower Bound                          │ +0.46     │
│ + Combinatorial Hypergeometric Lattice Sum                  │ +0.22     │
│ + Bachelier Option Integration for SUBSTITUTE Convexity     │ +0.25     │
│ + Information-Dependent Ride Hurdle                         │ +0.38     │
│ - WALLET_SNIPE (Bidding TE_theirs + 1 on everything)        │ -0.38 (X) │
│ - TAPE_SHIFT_DENY (Settling early to block forced fills)    │ -0.27 (X) │
│ - SHADE_CONTEST (Overbidding contested auctions)            │ -0.18 (X) │
│ - TRANSFORM on relative hand variance                       │ +0.00 (-) │
└─────────────────────────────────────────────────────────────┴───────────┘
```

### Why the Failed Features Failed:
1. **`WALLET_SNIPE` destroyed the salvage edge**: Against strong counterparties, contract PnL settles near zero; $+1.79$ of our $+1.86$ profit margin came purely from unspent TE salvage ($0.08 \times \Delta\text{TE}$). Outbidding opponents by $+1$ converted high-certainty cash salvage into low-utility powers.
2. **`TAPE_SHIFT_DENY` fought the Ride Hurdle**: Settling early to deny an opponent's shift powers sacrificed our Turn-6 optionality. The adaptive ride hurdle already prices spread contraction naturally.

---

## 5. System Architecture & Component Interactions

```mermaid
sequenceDiagram
    autonumber
    participant E as Game Engine
    participant B as qs_bot.py
    participant M as Market Making (quote)
    participant N as Negotiation (respond)
    participant A as Auction (bid)

    Note over E,B: Round Start (Coins Revealed)
    E->>B: bid(obs, offered)
    B->>A: Evaluate power values V(P) vs 0.08 salvage
    A-->>B: Return optimal bid vector
    B-->>E: Submit sealed bids

    Note over E,B: Negotiation Phase
    alt Bot is Maker
        E->>B: quote(obs)
        B->>M: Compute true straddle p_true & parity lo
        M-->>B: Return (best_lo, best_lo + best_w)
        B-->>E: Post opening quote
    else Bot is Taker
        E->>B: respond(obs, quote, turn)
        B->>N: Run Bayesian filter on quote midpoint
        alt Turn 6
            N-->>B: Execute dominant (ask, ask) option
        else Turns 2-5
            N-->>B: Evaluate Bachelier EV vs Adaptive Hurdle
        end
        B-->>E: Return Action (Accept / Counter)
    end
```

---

## 6. Execution & Verification Guide

### 6.1 Scoreboard Benchmarking
Run the full 38-bot benchmark suite across 1,200 deals per matchup:
```bash
python3 lab/scoreboard.py --bot lab/bot/qs_bot.py
```

### 6.2 Parallel Duel in the Arena
Run a head-to-head match between any two strategies with mirrored deal seeds:
```bash
python3 lab/arena.py --a lab/bot/qs_bot.py --b quantstorm-ps/strategies/rational.py --n_deals 100
```

### 6.3 Code Quality & Latency Constraints
- **Complexity**: Strict $O(1)$ analytical execution per step (zero Monte Carlo sampling).
- **Latency**: Mean runtime $\approx 0.8\text{ ms}$, max runtime $< 5.0\text{ ms}$ (comfortably within the $50.0\text{ ms}$ limit).
- **Compliance**: $100\%$ zero-forfeit, zero-clamp rate.
