# LAB NOTES — QuantStorm 2026 R1 "Divided Oracle"

**This file is the durable memory of this project. Read it first, every session.**

Last updated: after the 8:22 AM repo sync and the first board result (+84.83). Phases 0-3 complete; board diagnosis done.

---

## 0. Standing rules

1. **Read `quantstorm-ps/RULEBOOK.md` §§4–7 and this file before changing strategy code.**
2. The rulebook states: *"where this document and the code disagree, the code is authoritative."*
   Every claim that drives a design decision must be checked against `engine.py` / `game_config.py`,
   with a line reference recorded in §1 below. Do not act on recalled facts.
3. `git -C quantstorm-ps pull` and re-read `FAQs.txt` between phases. The organisers say both will be
   updated during the competition and **rules may change**; changes are announced on WhatsApp.
4. Never edit `engine.py` or `game_config.py`. The tournament runs its own copies.
5. **Nothing of ours lives inside `quantstorm-ps/`.** The organisers warn that re-fetching can
   overwrite or delete anything kept there. Our entry is `lab/bot/qs_bot.py`; the harness loads it
   from there and `backtester.py` accepts the absolute path fine.
6. **`README.md` line 3 carries a "Last Updated at" timestamp.** Check it against our clone every
   session:
   ```bash
   head -3 quantstorm-ps/README.md
   git -C quantstorm-ps fetch origin && git -C quantstorm-ps diff --stat HEAD origin/HEAD
   ```
   If it moved, **diff `engine.py` and `RULEBOOK.md` before pulling** — our edges are code-level
   readings and a patch could delete one.

### Repo sync log

| When | Change | Impact on us |
|---|---|---|
| 00:03 clone | — | baseline |
| **12:52 AM update** | `engine.py` bid-budget rule; rulebook §4 + §11 wording; README timestamp; starter_bot docstring | **Rule change, see §1. No impact on our edges** — turn-6, obligation and width mechanics untouched. Panel scores byte-identical after the pull. |
| **8:22 AM update** | `engine.py` Unicode box-drawing → ASCII (cosmetic only, zero logic); README gains sponsors + full leaderboard rules + submission timing | No logic impact. Both loaders read with explicit `encoding="utf-8"` (`bot_loader.py:237`, `sandbox.py:441`), so non-ASCII in a submission is safe — but our file is ASCII-only now anyway as free insurance. |

### Submission logistics (from the 8:22 AM README)

- **Live leaderboard**: https://www.tinyurl.com/quantstorm — cumulative PnL vs 10 hidden bots on set seeds.
- **Unlimited submissions, 10-minute cooldown.** Must use the Unstop-registered email or it is auto-rejected.
- Leaderboard is "for fun / an indication" and **does not represent final results**.
- **Google Form appears in the README at 11:00 PM, closes 11:59 PM.**
  **You may only upload ONCE to the form — the final strategy is a single irreversible choice.**

## Deadline

**11:59 PM IST, 17 Aug 2026.** Submission is via a Google Form to be posted in the repo README
(still not posted as of the 12:52 AM update — keep checking).

---

## 1. Spec digest — verified claims about the code

Each line is something I checked in the source, not something I remember from the rulebook.

### Structure
- Deal = 5 rounds; each round `reveal 4 → auction (1 power) → negotiation ≤6 turns → 1 contract`.
  All five contracts settle at once. `engine.py:1127-1240`.
- `S` = sum of 40 fair ±1 coins, 20 per seat. `E[S | my revealed] = k_mine`. Residual sd
  `sqrt(40 − 4r)` = `config.residual_sd(r)`.
- Maker alternates: seat 0 makes in rounds 1,3,5; seat 1 in 2,4. Inverted on the mirror leg.
  `engine.py:1148-1150`.
- Mirror: same coin vector, hands swapped, roles inverted. Two copies of one bot net **exactly 0.0**.
  Use this as the control in every experiment.

### Turn order — LOAD-BEARING
`N_TURNS = 6`. Turn 1 = Maker's opening quote. Turns 2..6 alternate **starting with the Taker**
(`engine.py:746-748`), so:

```
T1 maker(quote)  T2 taker  T3 maker  T4 taker  T5 maker  T6 taker
```

**The Taker always moves last.** The Maker's last action is T5.

### The turn-6 option (Edge 1)
- A counter's range is clamped *inside* the current range, and width is bounded only from **above**:
  `max_width = min(ask−bid, max(final_cap, (ask−bid) − MIN_REDUCTION))`. `engine.py:567-583`.
  **Width 0 is legal.** Countering tighter than `final_cap` is legal.
- If T6 ends without acceptance → forced fill at `(bid+ask)//2 + shift`, and the **last quoter is
  short** (`MIDPOINT_SIDE_RULE = "last_quoter_sells"`). `engine.py:784-808`.
- The forcer (last quoter) pays `FORCED_FILL_FEE = 2.0`. `engine.py:963-986`.
- ⇒ Taker at T6 may counter `(ask, ask)`, becoming short at exactly `ask`, for a 2.0 fee.
  **Taker's T6 menu: long@ask, short@bid, short@ask−2.** Third dominates second whenever width > 2.
  Payoff `max(v−ask, ask−v−2, bid−v)` ≈ `|ask − v| − 1`.

### Maker obligation (Edge 2 / 3)
`engine.py:908-960`:
```
straddle (open_bid <= S <= open_ask):  Taker pays Maker  3.0 * (1 − p_w)
miss:                                  Maker pays Taker  3.0 * p_w
always:                                Maker pays Taker  0.22 * (w − floor)
```
- `p_w = config.straddle_prob(r, w)` uses the **baseline** `unseen = 40 − 4r`. It does **not** know
  what the Maker actually knows.
- ⇒ An honest Maker breaks even at *every* width; `WIDTH_PREMIUM` is a pure `−0.22 × (w − floor)` tax.
- ⇒ A Maker who knows more than baseline (opponent read, FORESIGHT) straddles more often than `p_w`
  prices and is **paid `3.0 × (p_true − p_w)`**.
- `straddle_prob` is an exact lattice sum (`game_config.py:34-53`) and is a **step function** in `w`
  because the residual has fixed parity.

### Powers
| Power | Magnitude | Rounds | Once/deal | Effect |
|---|---|---|---|---|
| FORESIGHT | 16 | 1–5 | no | see `min(16, 4r)` of opponent's revealed coins |
| TRICK_ROOM | 3 | 1–5 | no | forced fill shifts 3 your way |
| SUBSTITUTE | 2 | 1–5 | no | your loss on that round's contract capped at 2 |
| STEALTH_ROCK | 2 | 1–4 | yes | persistent: all later forced fills shift 2 your way |
| TRANSFORM | 0 | 1–3 | yes | *option* to swap entire 20-coin hands |

- **`min(16, 4r)`: in rounds 1–4 FORESIGHT shows the opponent's ENTIRE revealed hand.** Only round 5
  is a sample (16 of 20).
- Slate is **drawn**, one power per round, from a stream keyed on the deal seed only; both seats face
  the same slate; the mirror replays it. `game_config.py:522-553`.
- Shift powers cancel exactly between seats; sign is `+mag` for the short seat. `engine.py:658-674`.
  `engine` is NOT importable from a submission — reimplement the sum from the table.
- TRANSFORM is consumed whether or not it is fired, so buying-and-declining is a defence.
  `engine.py:1181-1197`.

### Auction
- Blind first price, higher bid wins and **pays its own bid**. Equal non-zero → coin flip, winner pays.
  Both zero → nobody wins. `engine.py:864-890`.
- `TE_BUDGET = 24` per deal, no carry-over, no replenish. `TE_SALVAGE = 0.08` on the **difference** of
  unspent balances ⇒ 1 tick = 12.5 TE, whole budget = 1.92 ticks.
- **Bids totalling more than `te_mine` are ZEROED — the whole vector.** Changed 17 Aug 12:52 AM;
  it used to rescale proportionally. You contest nothing that round and the opponent takes the power
  uncontested for whatever they bid. It is counted as a clamp **and** warned about.
  `engine.py:355-375`. Overbidding is no longer a cheap way to spell "all-in".
  ⇒ Our `bid()` allocates greedily against a running balance, so it cannot exceed the budget by
  construction — there is no arithmetic that has to come out right for the bid to be legal.
- `obs.te_theirs` gives the opponent's remaining TE **exactly**.
- Winning bids are public on `obs.auction_log` (`round`/`seat`/`power`/`cost`). Losing bids stay private.

### Limits and failure modes
- Hard limit 50 ms per call; 5 violations then forfeit 250 PnL. On macOS/Linux an overrun is abandoned
  mid-frame and **forfeits the remainder of that deal**.
- `reset()` raising forfeits the whole deal to fallbacks — keep it short and total. `engine.py:277-281`.
- Fallbacks: `bid()`→`{}`, `quote()`→centred on 0 at **max** spread, `respond()`→`ACCEPT_BUY`,
  `use_transform()`→`False`.
- Statelessness is enforced: module re-executed per deal, fresh instance, stdlib restored, new
  interpreter per deal in the graded run. `--isolate` reproduces this.

---

## 2. Baselines (the zero)

3 seeds (7, 11, 23) × 60 deals/phase = 360 mirrored deals. Per-deal σ ≈ 13 ⇒ stderr ≈ 0.7 ticks/deal.
**Require ~2 stderr AND no regression against any single opponent before accepting a change.**

| Matchup | ticks/deal |
|---|---|
| `adaptive_bidder` vs `rational` | +2.61 |
| `adaptive_bidder` vs `naive_ev` | +5.30 |
| `rational` vs `naive_ev` | +1.17 |
| `starter_bot` vs `rational` | −1.17 (starter ≡ naive_ev) |
| any bot vs itself (mirrored) | **0.00 exactly** — control |

---

## 3. Experiment log

### Ablation ladder (Phase −1 research, 3 seeds × 120 deals)

| Stack | naive | rational | adaptive | mean |
|---|---|---|---|---|
| L0 rational-equivalent | +1.19 | −0.64 | −3.78 | −1.08 |
| L1 +quote at floor width | +1.82 | −0.84 | −3.12 | −0.71 |
| **L2 +maker centres on E[S]** | +4.80 | +4.25 | +1.43 | **+3.49** |
| L3 +FORESIGHT scaled estimator | +4.80 | +4.25 | +1.43 | +3.49 |
| **L4 +turn-6 force-sell** | +9.22 | +8.66 | +2.33 | **+6.74** |
| L5 +turn-5 maker point-collapse | — | — | — | +6.74 |
| L6 +auction bidding (adaptive's table) | +10.66 | +9.90 | +3.31 | +7.95 |
| **+never accept before T6 (both seats)** | +13.96 | +14.39 | +6.19 | **+11.51** |
| +round-5 width 4 when we have a read | +14.11 | +14.72 | +5.89 | **+11.58** |

### Confirmed positive
- **E1 turn-6 force-sell** (+3.3): never `ACCEPT_SELL` on the final turn.
- **E1b ride to turn 6** (+2.4 taker, +0.3 maker): accept-threshold → ∞ for both seats.
- **E2 maker centres on `E[S] = k_mine + read`** (+4.2): largest pricing gain. Reference bots use
  `k_mine` only and discard the read exactly when quoting.
- **E3 width at the floor** (+0.37) and **round-5 width 4 with a read** (+0.27).
- Auction bidding with `adaptive_bidder`'s table (+1.2).

### Confirmed negative / dead ends — DO NOT RE-RUN
- **FORESIGHT rescaling** `sum × 4r/len`: exactly 0.00. `min(16,4r)` means no rescale in rounds 1–4.
  Correct to implement, but worth nothing.
- **Turn-5 maker point-collapse**: 0.00, tested twice. The default centre-counter already lands there.

### Opponent-dependent — needs adaptive handling, not a constant
- **Counter geometry `far`** (push ask away from our value): +1.2 vs naive/rational,
  but **+5.9 → +0.8 vs adaptive**. `centre` is the robust choice. Tested: centre/far/near/ask.
- **Quote distortion** `centre = k_mine + α·k_theirs`: α=2.0 gives +3.4 vs quote-readers,
  −6.6 vs non-readers. Real exploit, opponent-dependent.
- **Shade**: 0.4 beats 0.6 vs non-bidders, loses to 0.6 vs `adaptive_bidder`. Key it off whether the
  opponent actually bids (`auction_log`, `te_theirs`).

### Optimal maker width by information state
`EV = 3.0·(p_true − p_w) − 0.22·(w − floor)`. `unseen` for a maker at round `r` who read the
opponent's quote at `r−1` is `40 − 4r − 4(r−1)`.

| Round | floor | blind: best w (EV) | with read: best w (EV) | read+FS |
|---|---|---|---|---|
| 1 | 4 | 4 (0.000) | 4 (0.000) | 4 (+0.063) |
| 2 | 4 | 4 (0.000) | 4 (+0.075) | 4 (+0.166) |
| 3 | 3 | 3 (0.000) | 3 (+0.142) | 3 (+0.246) |
| 4 | 3 | 3 (0.000) | 3 (+0.327) | 3 (+0.547) |
| 5 | 2 | 2 (0.000) | **4 (+0.695)** | **4 (+0.695)** |

Dominated widths (same straddle rate, more premium — never quote): 5 and 6 in rounds 1–4; 5 and 6 in
round 5; 9 in rounds 1–2.

---

## 4. Current best config — `lab/bot/qs_bot.py`

**Phase 0 and Phase 1 are DONE.**

Harness: `lab/arena.py` (seed panel 7/11/23/41/97 × 60 deals/phase = 600 mirrored deals; stderr
computed across *mirror pairs*, which is the low-variance unit — gives ~0.4 stderr, better than the
0.7 estimated from raw per-deal σ). `lab/opponents.py` holds the panel.

Bot design (all knobs are module constants at the top of `qs_bot.py`):
- `E[S] = k_mine + their_k`, where `their_k` combines FORESIGHT (raw sample sum — **not** rescaled;
  `engine.py:612-633` says unshown coins are mean-zero so the raw sum is the honest estimator and
  scaling up has ~12× the variance) and the most recent opening-quote read, by **inverse variance**.
  FORESIGHT variance `4r − n` (zero in rounds 1–4), read variance `4(r−r0) + READ_NOISE`.
- Quote: centre `E[S]`, width **solved online** against `config.straddle_prob` rather than tabulated
  (spec-derived, so also safe under §12 anti-copying).
- Respond: ride past every turn unless edge > `RIDE_THRESHOLD`; at the last turn take
  `max(v−ask, bid−v, (ask+shift)−v−2)`.
- Counters: centre on `v`, width `(ask−bid) − 1`.
- Auction: power values **derived from what each power does under our own play**, not copied.
  Notably `TRICK_ROOM = 3 × P_FORCED` and `STEALTH_ROCK = 2 × P_FORCED × rounds_left`, because we
  force far more often than the reference bots. Bids capped at `te_theirs + 1` (they cannot outbid
  their own balance, and `te_theirs` is exact).

### Phase 2/3 parameter sweeps (`lab/sweep.py`)

Run on the full panel. **The panel overturned two conclusions that the three reference bots had
supported** — this is the overfitting risk the plan named, caught in the act.

| Param | Shipped after sweep | Finding |
|---|---|---|
| `RIDE_THRESHOLD` | **2.0** | Earlier research on the 3 reference bots said *never accept before T6* (∞). On the full panel that is **wrong**: mean falls from +8.18 (at 2.0) to +7.55 (at 5.0) and keeps falling. Tight-quoting opponents punish riding past a real edge. `0.0` has the best worst-case floor; `2.0` the best mean. |
| `SHADE` | **0.15** | Monotone down to a genuine interior peak: 0.0→+5.53, 0.10→+8.72, **0.15→+8.92**, 0.20→+8.72, 0.35→+8.18, 0.55→+6.81. `SHADE=0` (never bid) is clearly bad — mostly because a 1-TE `Sniper` then takes every power (+1.29 vs +7.13). |
| `P_FORCED` | **0.15** | My shift-power model was too generous. 0.15→+8.47, 0.30→+8.18, 0.60→+6.81. |
| `READ_NOISE` | 2.0 | Flat, no signal across 0–10. Left as is. |

**Why the auction wants so little TE:** this bot's edge is pricing and the endgame, not powers. TE
salvage pays on the *difference* in unspent balances, so letting the opponent overpay for powers is
itself profitable. Bid enough to beat a sniper, not enough to win a bidding war.

`HeavyBidder` (published surface, zero shading) was added to the panel *because* the shade sweep was
being driven by a panel where 6 of 10 opponents barely bid. It scores +4.94, so the low shade is not
an artifact of a non-bidding panel.

### Panel scores (5 seeds × 120 deals)

Post-tuning (`RIDE_THRESHOLD=2.0, SHADE=0.15, P_FORCED=0.15`):

| Opponent | before tuning | **after tuning** |
|---|---|---|
| naive_ev | +13.54 | +13.32 ± 0.55 |
| rational | +12.95 | +12.90 ± 0.44 |
| adaptive_bidder | +4.62 | +4.54 ± 0.36 |
| CapQuoter | +10.95 | +12.41 ± 0.41 |
| FloorQuoter | +2.35 | **+7.35** ± 0.43 |
| FlatBidder | +1.47 | **+4.78** ± 0.42 |
| Sniper | +1.39 | **+5.71** ± 0.37 |
| T6Bot | +1.01 | **+3.44** ± 0.38 |
| RideKiller | +3.76 | +1.84 ± 0.35 |
| HeavyBidder | — | +4.94 ± 0.39 |
| Aggro | +1.85 | +0.71 ± 0.36 |
| **MEAN** | +5.39 | **+6.54** (worst: Aggro +0.71) |

**Beats every panel opponent.** Tuning bought a lot against the mid-tier archetypes but gave some
back against `RideKiller` and `Aggro` — both of which are built specifically to punish riding.
Those two are the tightest margins and the obvious next target.

### Health
- Self-play control: exactly `+0.000000000`. No seat-dependent bug.
- **`--isolate` matches in-process exactly** (+262.37 both, 30 deals seed 7 vs adaptive_bidder),
  re-verified after tuning AND after the 12:52 AM engine update.
- Timing under `--isolate`: avg 0.008 ms, **max 0.048 ms**. Budget 2 ms avg / 50 ms hard.
  (A long-lived arena process once showed a 1.71 ms max on a cold `straddle_prob` lattice cache;
  irrelevant against the 50 ms limit, and it does not appear under isolation.)
- Zero warnings, zero clamps, zero violations across the whole panel.
- `--validate`: passes every static check. **Only the metadata placeholders reject it.**

---

## 4b. BOARD RESULT #1 and what it taught us

Submitted config scored **+84.83 mean PnL/match** (total +2544.99 / 30 matches; a match is 20 deals,
so ~+4.24 ticks/deal). Baselines on the same board: adaptive_bidder -32, rational -40, naive_ev -66.
Clean: 0 clamps, 0 violations, 0 forfeits. **Slowest call 39.05 ms.**

Per-opponent: o01_raw_bid_sniper +127.22, o07_obligation_harvester +94.22, o02_te_opportunity_cost
+89.99, o05_transform_arbitrageur +88.30, o03_quote_compressor +86.20, o06_shift_power_camper +81.70,
o04_counterspy +80.15, o09_min_counter_squeeze +72.48, o10_foresight_deflation +71.82,
o08_forced_fill_engineer (truncated in the report -- lowest; **get this number next submission**).

### The 39 ms is NOT our code -- do not micro-optimise
Measured directly: our slowest path is **0.041 ms cold** in a fresh interpreter, **0.010 ms warm**,
0.024 ms worst across all round/foresight states. ~1000x under what the board recorded. The 39 ms is
interpreter start / per-deal module re-execution / GC / page fault -- what the five-violation
allowance exists to absorb. Added a `_width_cache` anyway (free), but there is nothing else to win.

### Settlement decomposition -- where the PnL actually is
Recomputed each component from public `DealResult` fields (ticks/deal, us = seat 0):

| Opponent | total | contract | obligation | forcing | salvage | forced% |
|---|---|---|---|---|---|---|
| naive_ev | +13.00 | +12.41 | +3.57 | -2.48 | -0.50 | 46% |
| adaptive_bidder | +6.12 | +3.46 | +0.27 | +0.67 | +1.72 | 7% |
| T6Bot | +4.57 | +2.40 | +0.22 | +0.16 | +1.79 | 2% |
| RideKiller | +2.75 | +0.39 | +0.22 | +0.34 | +1.79 | 3% |
| Aggro | +1.86 | **-0.51** | +0.22 | +0.36 | +1.79 | 4% |

Three conclusions that should shape all future work:
1. **Against strong opponents our contract PnL is ~0 or negative.** We win on **TE salvage** (+1.79,
   near the +1.92 theoretical max). We are NOT out-trading good bots. No headroom left in that term.
2. **The turn-6 edge is dead against good opponents** -- 46% forced fills vs naive_ev, 2-4% vs strong
   bots. They settle before the last turn. It only pays against wide, passive quoters.
3. **The obligation only pays against wide quoters** (+3.57 vs naive at width 5.9; +0.22 vs floor
   quoters at 3.4).

### Board reconstruction FAILED calibration -- do not tune against it
`lab/board_bots.py` reconstructs all ten from their names. Rank concordance with the real board is
**17/36 pairs = 47%**, i.e. no better than chance, and mine are systematically too strong. Treat them
as **adversarial stress tests, not a board proxy.** Do not tune parameters to them.

### The quote-trust vulnerability (real, measured, only partly fixable)
Our pricing rests on one unverified assumption: the opponent's opening midpoint is their revealed sum.
Against opponents that lie with the quote while pricing honestly internally:

| Opponent | our score |
|---|---|
| honest FloorQuoter | **+8.54** |
| compress toward 0 (x0.4) | +0.65 |
| constant-zero quote | **-2.04** |
| broadcast the INVERSE | **-8.31** |

**Detection does not work.** Every detector tried failed to fire, because compress/invert/zero all
produce arithmetically plausible reads (|k| <= 4r, right parity, no impossible cross-round jump):
- arithmetic bound clamp: catches only inflation (-0.02 honest, +1.7 vs inflater). Kept -- it is free.
- cross-round consistency: never fires.
- behavioural (their trade bounds their value): **never fires** -- our quote midpoints and their reads
  live in disjoint rounds, since exactly one of us is Maker each round.

**>>> ALL OF THE BELIEF-LAYER WORK BELOW WAS SHIPPED, LOST POINTS ON THE BOARD, AND HAS BEEN
REVERTED. DO NOT RE-APPLY IT. <<<**

The weak prior (PRIOR_WEAKNESS=8.0) and the READ_NOISE_QUOTE/TRADE split measured as ~free on the
local panel (-0.05 ticks/deal) and slightly BETTER on the board reconstructions. The real board
disagreed and the score went DOWN. Two lessons, and the second is the important one:

1. The board reconstructions in `lab/board_bots.py` are worthless as a predictor -- already known
   (47% rank concordance), now confirmed the expensive way. **Never ship on their evidence.**
2. A change that is "free" on the local panel is NOT free. The local panel is 11 honest-ish bots;
   -0.05 there told us nothing about 10 hidden bots. **Only the board can validate a change, and
   the board costs a submission.** Prefer changes with a large local effect; ignore small ones.

**The only real defence is not trusting the read, and it was priced and REJECTED.** Full shrinkage
costs 1.33 ticks/deal vs honest opponents to buy 3.5 vs a liar -- break-even needs ~27% of the field
to distort heavily. The rulebook tells everyone distortion does not pay, so that is bad business.
Settled on a **weak prior (PRIOR_WEAKNESS=8.0)** at the knee of the curve: costs 0.05 honest,
measured slightly BETTER on the board reconstructions, trims worst-liar -6.63 -> -5.86.

Kept the asymmetric structure (READ_NOISE_QUOTE=2 / READ_NOISE_TRADE=5) because it is the right
shape: a mis-centred **quote** costs a bounded obligation, a mis-priced **trade** is unbounded.

### ROLLBACK (after board result #2 went down)

Reverted to the exact +84.83 configuration. Verified by panel signature, which reproduces to the
decimal: naive +13.32 / rational +12.90 / adaptive +4.54 / CapQuoter +12.41 / FloorQuoter +7.35 /
FlatBidder +4.78 / Sniper +5.71 / T6Bot +3.44 / RideKiller +1.84 / HeavyBidder +4.94 / Aggro +0.71,
**MEAN +6.54**; isolate duel +262.37. Use this table as the fingerprint of the known-good build.

Reverted: `PRIOR_WEAKNESS`, `READ_NOISE_QUOTE`/`READ_NOISE_TRADE` split, the read clamp, the width
cache, and the `_their_k`/`_est` signature changes. Restored `READ_NOISE=2.0`, `READ_TRUST=1.0`.

**Kept** (comment-only, cannot affect play -- proven by the exact panel match): the file is pure
ASCII. Everything else is byte-equivalent in behaviour to the +84.83 build.

### Bugs found and fixed this block (NOTE: these fixes were reverted with the rest)
1. **`_est(self, obs, noise=READ_NOISE_TRADE)`** -- a default argument binds the module constant at
   *def* time, so the knob was frozen at import and every sweep of it read as perfectly flat. Now
   resolved at call time. *Any future tunable must not be a default argument.*
2. **No prior in `_their_k`** -- with a single source, inverse-variance weighting returns it at face
   value, so the variance was computed and discarded and `READ_NOISE` was inert.
3. **`READ_TRUST` was dead** -- referenced only in `_unseen`, doing nothing. Removed.
4. File is now **pure ASCII** (was 385 box-drawing chars). Not strictly needed -- both loaders specify
   utf-8 -- but free.

### Adaptive-behaviour probe (17 Aug, post-v6) -- rejected

Two within-deal adaptations were implemented and swept, then removed from the submission:

- **Forced-fill-rate power valuation:** updated `TRICK_ROOM` / `STEALTH_ROCK` from completed
  contracts' public `forced` flags, with a three-round empirical-Bayes prior.  It was directionally
  plausible -- forced fills are 2--4% against strong bots but 46% against naive_ev -- yet the quick
  candidate lost to v6 head-to-head (**-0.21 +/- 0.13** ticks/deal) and its honest-panel movement was
  below the 0.5-tick shipping threshold.
- **Turn-5 rider detector:** after an opposing Maker reached turn 5, reduced our later Taker
  acceptance bar to pre-empt its final-range squeeze.  A 3-seed x 120-deal full-panel sweep found
  `0.0` discount best on both mean and floor; discounts 0.2--0.8 all regressed, including against
  RideKiller itself.
- **SUBSTITUTE-aware turn-6 utility:** compared the actual capped contract payoff before applying
  the separate forcing fee.  This is mathematically correct, but it selected exactly the same
  actions: full 5-seed x 240-deal panel scores and a direct v6 matchup were both **+0.00**.

**Do not ship either without a genuinely new signal.**  They observe real behaviour but do not predict
the next round well enough in a five-round deal.  The working bot remains exact v6 behaviour.

---

## 5. Open questions (backlog)

**Answered so far:**
- ~~Is ride-to-T6 exploitable?~~ **Yes.** `RideKiller` and `Aggro` are the two tightest matchups
  (+1.84, +0.71). Countering them is now the top priority.
- ~~Re-derive power values against our own style.~~ Done — derived from what each power does under our
  play, then `P_FORCED` swept to 0.15. Shift powers turned out **less** valuable than I predicted,
  not more.
- ~~Shade.~~ Swept; interior optimum at 0.15.

**Still open, in priority order:**
1. **Beat `RideKiller` and `Aggro`.** Both exploit the fact that our counters centre on our own value,
   which makes our last-turn option cheap for them to neutralise. Needs a maker-side response: detect
   an opponent that collapses the range on T5, and price the T6 option accordingly.
2. **Counter geometry, properly.** Only 4 fixed policies ever tried (`centre`/`far`/`near`/`ask`);
   `centre` won on robustness. The real question is where to steer the range on T2–T5 given that T6
   is an option on the ask. Still the largest unexplored lever.
3. **Adaptive knobs.** `SHADE` and quote-centre α are both strongly opponent-dependent. Classify the
   opponent within the deal (do they bid? do they read quotes? do they collapse on T5?) from
   `auction_log`, `te_theirs`, and their opening quotes, then switch.
4. **`DENIAL_WEIGHT` / TRANSFORM.** Repo ships 0.0 and flags it as stale from the old 40-TE spec.
   Our `_power_value` currently gives TRANSFORM 1.4 flat when flat-handed, 0 otherwise. Untuned.
5. **TE endgame.** We cap bids at `te_theirs + 1` but do not otherwise exploit knowing their exact
   balance — e.g. once they are broke, every remaining power is free.
6. **SUBSTITUTE × T6** — loss capped at 2 makes the forced sell nearly free that round; currently
   only crudely handled (it lowers the ride bar).
7. **`FLAT` threshold and the FORESIGHT/SUBSTITUTE coefficients** (`0.35`, `0.45`) are hardcoded
   inside `_power_value` and have never been swept. Promote them to module constants first.

---

## 6. Strategic tension to remember

Round-robin score is the **sum** across the field → rewards mean performance → favours the aggressive,
opponent-dependent settings. The Stage-1 gate is **pass/fail against an unpublished strategy** →
rewards robustness. Resolution: robust core, with the exploitative knobs made *adaptive within the
deal* rather than fixed at an exploitative constant.

## 7. Blockers

- **Metadata**: need real Name / College / Roll Number. Placeholders are rejected by `bot_loader.py`.
- **Submission form** not yet posted in the README.
