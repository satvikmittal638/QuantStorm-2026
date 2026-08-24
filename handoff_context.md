# Session Snapshot — QuantStorm 2026 R1 "Divided Oracle"

**Written:** 17 Aug 2026, mid-competition. **Deadline: 11:59 PM IST, 17 Aug 2026.**

> **Read `lab/LAB_NOTES.md` and `lab/versions/VERSIONS.md` next.** They are the durable
> memory of this project and contain the full experiment log, including negative results.
> This file is the orientation layer, not a replacement for them.

## Critical logistics (get these wrong and nothing else matters)

- **Submission is via a Google Form that appears in the repo README at 11:00 PM and closes at
  11:59 PM. You may upload ONCE. The final strategy is a single irreversible choice.**
- The **live leaderboard** (https://www.tinyurl.com/quantstorm) is separate: unlimited
  submissions, **10-minute cooldown**, must use the Unstop-registered email or it is
  auto-rejected. It scores against 10 hidden bots and "does not represent final results".
- The organisers have **changed `engine.py` twice mid-competition**. Before any work:
  ```bash
  head -3 quantstorm-ps/README.md            # line 3 carries "Last Updated at: <time>"
  git -C quantstorm-ps fetch origin && git -C quantstorm-ps diff --stat HEAD origin/HEAD
  git -C quantstorm-ps diff HEAD origin/HEAD -- engine.py RULEBOOK.md   # DIFF BEFORE PULLING
  ```
  Our edges are code-level readings of `engine.py`; a patch could delete one. Repo was current
  as of this snapshot (README timestamp 8:22 AM).
- **Nothing of ours lives inside `quantstorm-ps/`** — re-fetching can overwrite it. Our entry is
  `lab/bot/qs_bot.py`.

---

## 1. Current Algorithmic Strategy & Math

### The game in one paragraph

Hidden score `S` = sum of **40** fair ±1 coins; 20 dealt to each seat. Each round 4 more of
*your own* coins are revealed to you. A deal is 5 rounds of
`reveal → blind first-price TE auction (1 power) → ≤6-turn negotiation → 1 contract`. All five
contracts settle at once: long gets `S − p`, short gets `p − S`, plus four transfers (maker
obligation, 2.0 forcing fee, SUBSTITUTE refunds, TE salvage at 0.08 × the *difference* in
unspent balances). Matches are mirrored — same coins, hands swapped, roles inverted — so **two
copies of the same bot score exactly 0.00**. Every number we quote is a difference against that.

### Edge 1 — the Taker owns the last turn

`N_TURNS = 6`. Turn 1 is the Maker's quote, then turns alternate **starting with the Taker**:

```
T1 maker(quote)   T2 taker   T3 maker   T4 taker   T5 maker   T6 taker
```

The Taker always moves last. A counter is clamped *inside* the standing range and its width is
bounded only **from above** (`engine.py` `_sanitise_response`), so a **width-0 counter is
legal**. The Taker can therefore counter `(ask, ask)` on the final turn: the negotiation ends,
the last quoter is short by `MIDPOINT_SIDE_RULE = "last_quoter_sells"`, and the fill lands at
exactly `ask`, for the 2.0 forcing fee.

So the Taker's final-turn menu is **three** options, not two:

```
long at ask          short at bid          short at ask, minus 2
payoff = max(v - ask,  bid - v,  (ask + shift) - v - 2)   ~=  |ask - v| - 1
```

Consequences: **never `ACCEPT_SELL` on the last turn**, and the option is worth enough that we
do not trade earlier unless the edge clears a bar.

**The bar is a fraction of the spread, not a constant** (`RIDE_FRACTION = 0.8`). What we give up
by trading early is that option, whose value is bounded by the spread on the table — so a flat
threshold is the wrong *shape*. This was worth +0.48 ticks/deal and lifted the worst matchup
from +0.71 to +2.17.

### Edge 2 — price on E[S], not on your own coins

`E[S] = k_mine + (their revealed sum)`. Their sum is readable: an honest Maker centres its
opening quote on its own revealed sum, and `obs.contracts` carries `open_bid`/`open_ask` for
**every past round**, not just the current one. The reference bots latch only the current
round's quote and so have no read at all in rounds where they are the Maker — exactly when it
is worth most.

`_their_k` combines sources by **inverse variance**:

| source | estimate | variance |
|---|---|---|
| FORESIGHT leak | `sum(obs.foresight)` (raw, **not** rescaled) | `4r − n` |
| quote read at round `r0` | midpoint of their opening | `4(r − r0) + READ_NOISE` |

The raw sample sum is the honest FORESIGHT estimator — unshown coins are mean-zero, so scaling
up to hand size is unbiased but carries ~12× the variance. Because `min(16, 4r)`, **in rounds
1–4 the leak covers their entire revealed hand and the term is exact.**

### Edge 3 — parity, and the obligation lattice

**`S` is always EVEN** — it is a sum of `N_COINS = 40` coins of ±1 and 40 is even. Half the
integer prices in any quote are values the score can never take. How many *reachable* values a
window covers depends on where its low end sits:

| width | `lo` even | `lo` odd |
|---|---|---|
| 2 | **2** | 1 |
| 3 | 2 | 2 |
| 4 | **3** | 2 |
| 8 | **5** | 4 |

At the round-5 floor of width 2 that is **double the straddle rate for free**.

The maker obligation is:

```
straddle (open_bid <= S <= open_ask):  Taker pays Maker  3.0 * (1 - p_w)
miss:                                  Maker pays Taker  3.0 * p_w
always:                                Maker pays Taker  0.22 * (w - floor)
```

`p_w = config.straddle_prob(r, w)` prices the **canonical alignment** and a Maker who knows only
its own coins. We are neither — we align to the parity of `S` and we have a read — so **any
coverage we gain is paid to us at `3.0 × (p_true − p_w)`**. The bot therefore computes its own
true straddle rate exactly with `math.comb` and solves **width and alignment jointly**.

Verified as parity, not a directional bias:

| variant | honest panel |
|---|---|
| align EVEN | **+7.26** |
| align ODD | +6.36 |
| always +1 (direction only) | +6.79 |
| control | +6.83 |

Symmetric around the parity, direction-only control flat. **It does NOT pay on counters or on
the forced-fill price** (both measured negative) — only the opening quote is lattice-scored.

### The auction

TE budget 24/deal, no carry-over. `TE_SALVAGE = 0.08` on the *difference* in unspent balances,
so **1 tick = 12.5 TE and the whole budget is worth 1.92 ticks**. Power values are **measured by
free-grant ablation**, not guessed (see §4 for the caveat):

```
POWER_TICKS = {
    "FORESIGHT":    {1: 1.54, 2: 1.32, 3: 2.38, 4: 3.14, 5: 1.49},
    "TRICK_ROOM":   {1: 0.42, 2: 0.31, 3: 0.09, 4: 0.00, 5: 0.00},
    "SUBSTITUTE":   {1: 1.34, 2: 1.26, 3: 1.39, 4: 1.67, 5: 2.55},
    "STEALTH_ROCK": {1: 0.00, 2: 0.00, 3: 0.00, 4: 0.00, 5: 0.00},
    "TRANSFORM":    {1: 0.00, 2: 0.00, 3: 0.00, 4: 0.00, 5: 0.00},
}
```

Bid = `ticks / TE_SALVAGE * SHADE` with `SHADE = 0.30`, capped at `te_theirs + 1` (they cannot
outbid their own balance and `obs.te_theirs` is **exact**), then allocated greedily against a
running budget.

**Where our PnL actually comes from** (settlement decomposition, ticks/deal):

| Opponent | total | contract | obligation | forcing | salvage | forced% |
|---|---|---|---|---|---|---|
| naive_ev | +13.00 | +12.41 | +3.57 | −2.48 | −0.50 | 46% |
| adaptive_bidder | +6.12 | +3.46 | +0.27 | +0.67 | +1.72 | 7% |
| RideKiller | +2.75 | +0.39 | +0.22 | +0.34 | +1.79 | 3% |
| Aggro | +1.86 | **−0.51** | +0.22 | +0.36 | +1.79 | 4% |

**Read this carefully before optimising anything:** against strong opponents our contract PnL is
~0 and most of our margin is **TE salvage** (+1.79 of +1.86 vs Aggro, against a +1.92 theoretical
max). We are not out-trading good bots. Also, the turn-6 edge is **dead** against them — forced
fills are 46% vs `naive_ev` but only 2–4% vs competent opponents.

---

## 2. File Tree & Architecture

```
/Users/dmitt/Desktop/QuantStorm/
├── handoff_context.md          <- this file
├── quantstorm-ps/              <- the organisers' repo, git clone, KEEP PRISTINE
└── lab/                        <- all of our work, never submitted
    ├── LAB_NOTES.md
    ├── arena.py
    ├── opponents.py
    ├── board_bots.py
    ├── scoreboard.py
    ├── sweep.py
    ├── bot/qs_bot.py           <- THE SUBMISSION (working copy)
    └── versions/
        ├── VERSIONS.md
        ├── v1_board_84.83.py
        ├── v2_ride_fraction.py
        ├── v3_all_insights.py
        ├── v4_parity_align.py
        ├── v5_exact_straddle.py
        └── v6_measured_powers.py
```

| File | What it does |
|---|---|
| `lab/LAB_NOTES.md` | Durable memory: verified spec claims with `engine.py` line refs, full experiment log including dead ends, standing rules. |
| `lab/bot/qs_bot.py` | **The submission** — the single `.py` file that gets uploaded; currently identical to `v6_measured_powers.py`. |
| `lab/arena.py` | Measurement harness: fixed seed panel, `duel()`, stderr computed across *mirror pairs* (the low-variance unit), self-play control. |
| `lab/opponents.py` | The honest sparring panel — 3 reference bots plus 8 archetypes (CapQuoter, FloorQuoter, FlatBidder, Sniper, T6Bot, RideKiller, HeavyBidder, Aggro). |
| `lab/board_bots.py` | Reconstructions of the 10 hidden leaderboard bots from their names — **weak evidence, see §4**. |
| `lab/scoreboard.py` | Scores a candidate against all four groups (honest / past versions / board recons / liars) in both ticks-per-deal and per-match units. |
| `lab/sweep.py` | Sweeps one module-level constant of the bot through the panel and prints the profile. |
| `lab/versions/VERSIONS.md` | Immutable release log: every version, its scores, and the per-feature measurement tables. |
| `lab/versions/v*.py` | Frozen past releases — a candidate is measured head-to-head against them; **never edit these**. |
| `quantstorm-ps/` | The organisers' repo (engine, rulebook, backtester, reference bots). Never modify; re-fetch per the logistics section. |

**How to run anything:**

```bash
python3 lab/scoreboard.py                      # full four-group report on the working bot
python3 lab/scoreboard.py --bot lab/versions/v5_exact_straddle.py
python3 lab/sweep.py SHADE 0.15 0.3 0.5        # sweep a constant
Q=quantstorm-ps; B=lab/bot/qs_bot.py
python3 $Q/backtester.py --validate $B         # must print ACCEPTED
python3 $Q/backtester.py --bot1 $B --bot2 $Q/strategies/adaptive_bidder.py --quiet --n_deals 30 --seed 7 --isolate
```

---

## 3. Core Code Implementation

Full file is `lab/bot/qs_bot.py` (~470 lines, heavily commented). The load-bearing parts:

### Constants

```python
RIDE_FRACTION = 0.8    # early-trade bar as a fraction of the current spread
READ_NOISE    = 2.0    # extra variance on a quote-derived read
READ_TRUST    = 1.0    # how much of a read counts when sizing our own width
SHADE         = 0.30   # first-price shading
FLAT          = 1      # |revealed sum| at or below which a hand is "flat"
```

### Belief

```python
def _refresh(self, obs) -> None:
    """Harvest opponent opening quotes from every contract so far."""
    for c in obs.contracts:
        if c.maker_seat != self.seat and c.round not in self.reads:
            self.reads[c.round] = (c.open_bid + c.open_ask) / 2.0

def _their_k(self, obs):
    """Estimate the opponent's revealed sum, with its variance."""
    parts = []
    n = len(obs.foresight)
    if n:
        parts.append((float(sum(obs.foresight)), float(4 * obs.round - n)))
    if self.reads:
        r0 = max(self.reads)
        parts.append((self.reads[r0], 4.0 * (obs.round - r0) + READ_NOISE))
    if not parts:
        return None
    for est, var in parts:
        if var <= 0.0:
            return est, 0.0          # exact; nothing else can improve it
    wsum = sum(1.0 / var for _, var in parts)
    est = sum(e / var for e, var in parts) / wsum
    return est, 1.0 / wsum

def _est(self, obs) -> float:
    tk = self._their_k(obs)
    return float(obs.k_mine) + (tk[0] if tk else 0.0)
```

### Parity-exact straddle and the quote

```python
def _cover(self, m: int, a: int, b: int) -> float:
    """P(a <= Y <= b) for Y a sum of `m` fair +-1 coins.

    Y has the parity of m, so half the integers in [a, b] carry no mass at all
    -- which is the whole reason quote alignment matters.
    """
    if m <= 0:
        return 1.0 if a <= 0 <= b else 0.0
    total = 0
    for j in range(a, b + 1):
        if (j - m) % 2:
            continue                     # wrong parity: Y cannot land here
        k = (j + m) // 2
        if 0 <= k <= m:
            total += comb(m, k)
    return total / (1 << m)

def quote(self, obs):
    """Solve width and alignment together against the obligation."""
    self._refresh(obs)
    cfg = self.config
    v = int(round(self._est(obs)))
    r, floor, cap = obs.round, obs.final_cap, obs.spread_cap
    unseen = self._unseen(obs)

    best_ev, best_lo, best_w = None, v - floor // 2, floor
    for w in range(floor, cap + 1):
        lo = v - w // 2
        if lo % 2:
            lo += 1                      # S is always even
        try:
            priced = cfg.straddle_prob(r, w)
        except Exception:
            continue
        true_p = self._cover(unseen, lo - v, lo - v + w)
        ev = (cfg.MAKER_OBLIGATION * (true_p - priced)
              - cfg.WIDTH_PREMIUM * (w - floor))
        if best_ev is None or ev > best_ev:
            best_ev, best_lo, best_w = ev, lo, w

    return (best_lo, best_lo + best_w)
```

### Negotiation (the main decision loop)

```python
def respond(self, obs, quote, turn: int):
    self._refresh(obs)
    bid, ask = quote

    # The current round's opening quote reaches us on turn 2 and only turn 2.
    if turn == 2 and not obs.is_maker and obs.round not in self.reads:
        self.reads[obs.round] = (bid + ask) / 2.0

    v = self._est(obs)
    fee = self.config.FORCED_FILL_FEE

    # -- the last turn -- only the Taker ever sees this
    if turn >= obs.n_turns:
        force_px = ask + self._shift(obs)
        options = (
            (v - ask,                  "ACCEPT_BUY"),
            (bid - v,                  "ACCEPT_SELL"),
            (force_px - v - fee,       ("COUNTER", ask, ask)),
        )
        return max(options, key=lambda o: o[0])[1]

    # -- every earlier turn -- ride unless the edge clears a spread-scaled bar
    bar = RIDE_FRACTION * (ask - bid)
    if "SUBSTITUTE" in obs.powers_mine:
        bar -= float(self.config.POWERS["SUBSTITUTE"]["magnitude"])

    edge_buy, edge_sell = v - ask, bid - v
    if edge_buy > bar and edge_buy >= edge_sell:
        return "ACCEPT_BUY"
    if edge_sell > bar:
        return "ACCEPT_SELL"

    w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
    c = max(bid, min(int(round(v)), ask - w))
    return ("COUNTER", c, c + w)
```

### Auction

```python
def bid(self, obs, offered):
    """Greedy allocation against a running balance -- CANNOT exceed budget."""
    budget = int(obs.te_mine)
    if not offered or budget <= 0:
        return {}

    wanted = []
    for name in offered:
        v = self._power_value(obs, name)
        if v <= 0.0:
            continue
        amount = int(v / self.config.TE_SALVAGE * SHADE)
        amount = min(amount, int(obs.te_theirs) + 1)   # te_theirs is exact
        if amount > 0:
            wanted.append((v, name, amount))

    out = {}
    for _, name, amount in sorted(wanted, key=lambda t: -t[0]):
        take = min(amount, budget)
        if take <= 0:
            break
        out[name] = take
        budget -= take
    return out

def use_transform(self, obs) -> bool:
    return False        # measured: never-fire 0.00 beats every conditional rule
```

### Version scoreboard (5 seeds × 120 mirrored deals per matchup)

| Version | honest | strong-subset | floor | board-recon | liars | **real board** |
|---|---|---|---|---|---|---|
| v1 | +6.54 | — | +0.71 | +2.69 | −2.96 | **+84.83** |
| v2 ride-fraction | +7.02 | — | +2.17 | +3.69 | −2.78 | — |
| v3 all-insights | +6.59 | — | — | — | — | — |
| v4 parity-align | +7.40 | — | +2.74 | +4.21 | −2.35 | — |
| v5 exact-straddle | +7.62 | +5.46 | +3.09 | +4.56 | −1.96 | — |
| **v6 measured-powers** | +7.22 | **+5.65** | **+4.26** | **+4.93** | **−0.66** | — |

---

## 4. Bugs, Edge Cases, or Warnings

### Live limitations of the current bot

1. **We lose to a quote-inverting opponent.** Our whole pricing layer trusts that the opponent's
   opening midpoint is their revealed sum. Against opponents that lie with the quote while
   pricing honestly internally: honest FloorQuoter **+8.54**, compressor +0.65, constant-zero
   **−2.04**, inverter **−8.31** (v6 improves the inverter to about −5.0).
   **Detection does not work** — every detector tried failed to fire, because compress/invert/zero
   all produce *arithmetically plausible* reads (`|k| ≤ 4r`, right parity, no impossible
   cross-round jump). The only defence is not trusting the read, which was **priced and
   rejected**: full shrinkage costs 1.33 ticks/deal against honest opponents to buy 3.5 against a
   liar, i.e. it needs ~27% of the field to distort heavily. **Do not re-litigate this without
   new evidence** — see the rollback below.
2. **Power values are opponent-dependent and the two measurements disagree in SHAPE.**
   Self-play says SUBSTITUTE *rises* through the deal (+1.34→+2.55) and STEALTH_ROCK is 0;
   measuring against the panel says SUBSTITUTE *falls* (+1.24→−0.06). `STEALTH_ROCK = 0` is a
   fact about *our own play* (we rarely reach a forced fill), not about the power. We shipped the
   self-play table; this is the least certain part of the bot.
3. **v6 vs v5 is an unresolved judgement call.** v6's honest-panel *mean* is 0.40 **lower** than
   v5. That is entirely from naive_ev/rational/CapQuoter — bots unlike the real field. Against
   every hard opponent v6 wins, the floor rises +1.17, and liars improve +1.30. I took that
   trade; it is arguable, not proven. **This is what the next step resolves.**

### Traps in the engine and the rules

4. **An over-budget bid vector is ZEROED, not rescaled** (changed 12:52 AM mid-competition). You
   contest nothing that round and the opponent takes the power uncontested. Our `bid()` allocates
   greedily so it cannot exceed budget by construction — keep that property.
5. **Statelessness is enforced, not requested.** Fresh module, fresh instance, restored stdlib,
   and a brand-new interpreter per deal in the graded run. Anything learned dies with the deal.
   This is why cross-deal opponent profiling is impossible, not merely hard.
6. **A `reset()` that raises forfeits the entire deal** to fallbacks. Keep it short and total.
7. **Timing.** Hard limit 50 ms/call, 5 violations → 250 PnL forfeit, and on Linux/macOS an
   overrun forfeits *the rest of the deal*. The board reported a **39.05 ms slowest call**, but
   our own compute is **0.041 ms cold / 0.010 ms warm** — measured directly. The 39 ms is
   environmental (interpreter start, GC, page fault). **Do not micro-optimise our arithmetic; it
   would buy nothing.**
8. **Permitted imports only:** `math, random, statistics, collections, heapq, bisect, itertools,
   functools, typing`. We use `random` and `math.comb`.
9. **Do not make a tunable a default argument.** `def _est(self, obs, noise=READ_NOISE_TRADE)`
   binds the constant at *def* time, so the knob froze at import and every sweep of it read as
   perfectly flat. This silently corrupted a whole tuning session.

### Methodology warnings (these cost us real points)

10. **A build that measured "free" locally LOST points on the real board and was rolled back.**
    The weak-prior / quote-vs-trade-noise-split build measured −0.05 on the honest panel and
    slightly *better* on the board reconstructions. The board disagreed. **Local deltas under
    ~0.5 ticks/deal are not shippable** — they carry no information about the 10 hidden bots.
11. **`lab/board_bots.py` failed calibration: 17/36 pairs = 47% rank concordance with the real
    board, i.e. no better than chance,** and the reconstructions are systematically too strong.
    Use them as adversarial stress tests. **Never tune against them.**
12. **Head-to-head alone is insufficient evidence.** An adverse-selection correction beat v2
    head-to-head by +0.50 and *lost* on both the honest panel and the recons — it was exploiting
    v2 specifically. Require the honest panel to agree.
13. **Read de-biasing: correct in theory, harmful in practice — and a warning about us.**
    A strong opponent's opening midpoint is not their `k`; it is `k_theirs + their estimate of
    our k`, and their estimate of us is *our own last broadcast midpoint*, which we know exactly.
    Subtracting it back out (`read = mid − lambda * our_last_mid`) is therefore *correct* against
    any opponent who prices on `E[S]`. It measured **monotonically worse on every group**
    (honest +6.99→+3.94, STRONG +5.49→+2.23, board +5.08→+3.14, liars −0.29→−2.89 as lambda goes
    0→1) while winning **monotonically head-to-head against v6** (+0.89→+4.00). It is right about
    E[S]-pricers and wrong about the plain k-quoters that dominate the panel. **Do not ship it
    without a detector**, and detection has failed every time it has been attempted here.
    *This is the single cleanest example in the project of why head-to-head alone is not evidence.*
14. **We are only mildly exposed to that attack, and quoting on `E[S]` is still right.** Against a
    purpose-built de-biasing opponent v6 still scores **+4.83**. The alternative — broadcast only
    `k_mine` while trading on `E[S]` — is far worse everywhere (honest **+4.72** vs +6.99, STRONG
    +3.43 vs +5.49, board +3.31 vs +5.08, and it drops to +1.34 against the de-biaser anyway).
    **Edge 2 is load-bearing; do not weaken the quote to hide information.**
15. **Dead ends, do not re-run:** confidence-scaled acceptance bar (the spread already proxies
    confidence — floors narrow 4,4,3,3,2 exactly as certainty rises); parity on counters or on
    the forced-fill price (both negative); FORESIGHT rescaling (exactly 0.00); swap-aware belief
    reset after TRANSFORM (moved R2 from −1.28 to −1.16, not the mechanism); and all eight
    auction-tape/opponent-modelling features in `v3_all_insights.py` (every one neutral or
    harmful; the combination loses −0.98 to v2).

---

## 5. Immediate Next Step

**Put v5 and v6 on the live leaderboard, 10 minutes apart, and keep whichever scores higher.**

This is the single highest-value action available and it costs nothing but time. v5 and v6
disagree, the disagreement is a genuine judgement call (§4 item 3), and the leaderboard is the
only instrument that has ever resolved one of these correctly. Both files are frozen and
validated.

```bash
# 1. confirm the repo has not moved (organisers have patched engine.py twice)
head -3 quantstorm-ps/README.md
git -C quantstorm-ps fetch origin && git -C quantstorm-ps diff --stat HEAD origin/HEAD

# 2. validate whichever file you are about to upload -- must print ACCEPTED
python3 quantstorm-ps/backtester.py --validate lab/versions/v6_measured_powers.py
python3 quantstorm-ps/backtester.py --validate lab/versions/v5_exact_straddle.py

# 3. upload v6 to the leaderboard, wait out the 10-minute cooldown, upload v5,
#    and record BOTH scores in lab/versions/VERSIONS.md before doing anything else.
```

Interpretation rule, fixed in advance so the result cannot be rationalised afterwards:

- **v1 scored +84.83.** Treat a difference of less than ~10 points as noise (the board itself
  says "a few points of difference is noise" over 30 matches).
- If v6 > v5 by more than noise → v6 is the submission candidate; the strong-opponent trade was
  right.
- If v5 > v6 by more than noise → revert to v5 (`cp lab/versions/v5_exact_straddle.py
  lab/bot/qs_bot.py`) and **discard the panel-measured power table**.
- If both are within noise of each other, prefer **v6** for its much better worst-case floor
  (+4.26 vs +3.09) and liar robustness (−0.66 vs −1.96), since the round robin sums PnL across
  the whole field.

**Also worth recovering on that submission:** `o08_forced_fill_engineer`'s score was truncated
out of the only board report we have. It was v1's worst matchup and we still do not know its
value.

**Then, and only then**, consider further work. The largest *unexploited* quantity is **contract
PnL against strong opponents**, which the decomposition shows is ~0 — every current edge lives in
the obligation, the salvage, or the endgame option, and none of them out-trades a good bot.
Nobody has attacked that directly.

**Do not** spend the last hour on a new idea. The form is one-shot at 11:00 PM and closes at
11:59 PM; have the chosen file validated and ready well before then.
