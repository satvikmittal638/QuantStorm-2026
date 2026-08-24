# Version archive

Naming: `v<N>_<what-it-is>.py`. Once a file lands here it is **immutable** --
it is the thing a later candidate is measured against, so editing it destroys
the comparison. Working copy is always `lab/bot/qs_bot.py`.

Release checklist before archiving a new version:
1. `python3 lab/scoreboard.py` -- must beat the previous version head-to-head.
2. `--validate` ACCEPTED, `--isolate` identical to in-process, self-play 0.00.
3. Record the board score here once it comes back.

| Version | Board score | Honest panel | Notes |
|---|---|---|---|
| `v1_board_84.83.py` | **+84.83** | +6.54 | Known good. Turn-6 option, E[S] quoting, online width solve, greedy bid allocator. `RIDE_THRESHOLD=2.0, SHADE=0.15, P_FORCED=0.15, READ_NOISE=2.0`. |
| `v2_ride_fraction.py` | *(untested on board)* | **+7.02** | `RIDE_THRESHOLD=2.0` flat -> `RIDE_FRACTION=0.8` of the current spread. Improves EVERY group: honest +6.54->+7.02, board-recon +2.69->+3.69, floor +0.71->+2.17, liars -2.96->-2.78. Head-to-head vs v1 is a dead tie (-0.07 +/- 0.13). Biggest movers are exactly our weakest matchups: o08_forced_fill_engineer +0.55->+5.82, Aggro +0.71->+5.23. |
| `v3_all_insights.py` | *(not submitted)* | +6.59 | **All eight user-suggested features, fully implemented and measured. Every one is neutral or harmful; the combination loses -0.98 head-to-head to v2.** Kept because the code is correct and tunable -- every feature is behind a named constant, and setting them all to zero reproduces v2 EXACTLY (verified: vs-v2 = +0.00). |
| `v4_parity_align.py` | *(not submitted)* | +7.40 | **S is always EVEN** (sum of 40 coins of +-1). Align the opening quote's `lo` to even parity. honest +7.02->+7.40, board +3.69->+4.21, liars -2.78->-2.35. Beats v2 head-to-head +0.46. |
| `v5_exact_straddle.py` | *(current)* | **+7.62** | Solve width AND alignment jointly against our TRUE straddle rate, computed exactly with `math.comb` instead of `config.straddle_prob` (which prices the canonical alignment and a Maker who knows only its own coins). honest +7.40->+7.62, board +4.21->+4.62, liars -2.35->-1.91. |
| `v6_measured_powers.py` | *(current)* | +7.22 | Power values MEASURED by free-grant ablation instead of guessed; `SHADE` 0.15->0.30; TRANSFORM never bought and never fired. Trades weak-opponent score for strong-opponent score: STRONG subset +5.46->+5.65, **floor +3.09->+4.26**, board +4.56->+4.93, liars -1.96->-0.66. Beats v5 head-to-head by ~+3. |
| `v7_convexity_engine.py` | *(current candidate)* | **+7.25** | **SUBSTITUTE convexity engine (Bachelier option model for capped loss) + Shift reservation price + Opponent option defense + SHADE=0.33.** Beats v6 head-to-head by **+1.49 +/- 0.24** (+29.9/match), beats v5 by **+3.05 +/- 0.37**, beats v1 by **+3.70 +/- 0.36**. New highest floor: **+4.60 vs RideKiller**. Board recon: **+5.20**. |
| `v8_adaptive_engine.py` | *(new peak)* | **+5.22 (honest)** | **Online Bayesian Opponent Profiler + Inventory-Skewed Market Making (TE as inventory) + Dynamic Game-Theoretic Auction Sizing (replaces 25-cell constant matrix).** Beats v7 head-to-head by **+1.00 +/- 0.30** (+19.9/match), beats v6 by **+1.17 +/- 0.41**, beats v5 by **+1.48 +/- 0.50**, beats v1 by **+1.89 +/- 0.49**. |
| `v9_adaptive_engine.py` | *(previous peak)* | **+6.13 (honest)** | STEALTH_ROCK Persistent Valuation (+2 on all remaining forced fills, force_rate=0.25) + Adaptive Information-Dependent Ride Hurdle. |
| `v10_first_principles.py` | *(new peak: +128.7/match)* | **+6.43 (honest)** | **Zero-hardcoding First-Principles Engine: Bellman continuation value negotiation + Exact standard-deviation reduction FORESIGHT valuation + Dynamic Beta-Binomial forced fill estimation + Precision ground-truth forensics.** Beats ALL 9 past versions strictly (v1: +4.40, v7: +2.10, v8: +0.98, v9: +0.06). |
| *(belief-layer build)* | **LOWER** (rolled back) | +6.42 | Weak prior + quote/trade noise split + read clamp. Measured ~free locally, lost on the board. **Not archived on purpose** -- see LAB_NOTES; do not resurrect. |

## The head-to-head test

A candidate plays its ancestor directly. The mirror makes two identical bots
score exactly `0.00`, so any non-zero number is real signal with no baseline
to subtract -- this is the sharpest instrument we have, sharper than the
opponent panel.

**But it is not sufficient.** Beating v1 head-to-head only proves the
candidate exploits v1. It must ALSO hold up on the honest panel, because the
field is not made of our own bots.

## Hard-won rule

A change that measures under ~0.5 ticks/deal locally is **not shippable**.
The belief-layer build measured -0.05 (i.e. free) on the honest panel and
slightly positive on the board reconstructions, and it lost real points on
the real leaderboard. Local noise at that scale carries no information about
the ten hidden bots.


## v3 feature-by-feature measurement

Built UP from v2, one feature at a time (3 seeds x 100 mirrored deals).
v2 control: honest +6.83, board-recon +3.74. Setting every constant to zero
reproduces v2 exactly (vs-v2 +0.00), which is what makes these numbers clean.

| Feature | honest | board | vs-v2 | verdict |
|---|---|---|---|---|
| `TAPE_SHIFT_DENY` (deny their forced fill) | +6.62 | +3.42 | -0.27 | harmful; at 0.25-0.5 it is merely neutral |
| `TAPE_SUB_SKEPTIC` (distrust a SUBSTITUTE holder's quote) | +6.82 | +3.73 | +0.02 | neutral |
| `TAPE_DESPERATION_PULL` (FORESIGHT overpay => flat hand) | +6.73 | +3.64 | +0.00 | slightly harmful |
| `WALLET_SNIPE` (bid te_theirs+1 for a sure win) | +6.84 | +3.62 | **-0.38** | harmful |
| `SHADE_CONTEST` (shade by how contested the auction is) | +6.75 | +3.47 | -0.18 | harmful |
| `DISTRUST_GAIN` (quote vs where the round settled) | +6.79 | +3.74 | +0.00 | neutral |
| `SUB_BAIT_TIGHTEN` (quote tighter holding SUBSTITUTE) | +6.75 | +3.72 | +0.01 | neutral |
| TRANSFORM on relative hand strength | +6.75 | +3.71 | +0.00 | neutral |

### Why the two biggest losers lose

**`WALLET_SNIPE` spends the thing that is actually our edge.** The settlement
decomposition showed that against strong opponents our contract PnL is ~0 and
+1.79 of our +1.86 margin is TE SALVAGE. Buying guaranteed-cheap powers
converts salvage (banked, certain) into powers (worth less to this bot than
to the reference bots, because our edge is pricing and the endgame). Measured
directly vs FloorQuoter: snipe OFF +7.74, snipe ON +7.39.

**`TAPE_SHIFT_DENY` fights `RIDE_FRACTION`.** Settling early to deny an
opponent's forced fill gives up the last-turn option, and v2's ride bar
already adapts to the spread. Two mechanisms pulling the same lever in
opposite directions.


## The parity edge (v4/v5) -- mechanism, and where it does NOT apply

`S` is a sum of `N_COINS` coins of +-1 and `N_COINS` is even, so **S is always
even**. Half the integer prices in any quote are values the score can never
take. How many reachable values a window covers depends on where its low end
sits:

| width | lo even | lo odd |
|---|---|---|
| 2 | **2** | 1 |
| 3 | 2 | 2 |
| 4 | **3** | 2 |
| 8 | **5** | 4 |

At the round-5 floor of 2 that is double the straddle rate for free. The
obligation charges `config.straddle_prob(r, w)`, which prices the CANONICAL
alignment, so any coverage we gain by aligning better is paid to us.

Verified as parity, not a directional bias:

| variant | honest |
|---|---|
| align EVEN | **+7.26** |
| align ODD | +6.36 |
| always +1 (direction only, no parity) | +6.79 |
| v2 control | +6.83 |

Symmetric around the parity, with the direction-only control flat.

**It does NOT pay on counters or on the forced-fill price** -- both measured
NEGATIVE (counter-even honest +6.84 vs +7.26). That is the mechanism
confirming itself: only the OPENING quote is scored against a lattice-computed
straddle probability. Elsewhere a price is just a price, and moving it off our
value estimate to chase parity costs more than the lattice returns.


## Power values: measured, and opponent-dependent (v6)

Free-grant ablation -- give one seat one power in one round, both seats
otherwise the same bot, and read the residual. Two identical bots net exactly
0.00 over a mirrored match, so the residual IS the value.

**Measured in SELF-PLAY** (ticks):

| power | R1 | R2 | R3 | R4 | R5 |
|---|---|---|---|---|---|
| FORESIGHT | +1.54 | +1.32 | +2.38 | +3.14 | +1.49 |
| TRICK_ROOM | +0.42 | +0.31 | +0.09 | 0.00 | 0.00 |
| SUBSTITUTE | +1.34 | +1.26 | +1.39 | +1.67 | +2.55 |
| STEALTH_ROCK | 0.00 | 0.00 | 0.00 | 0.00 | -- |
| TRANSFORM | -0.26 | -1.28 | +0.10 | -- | -- |

**Measured against the PANEL** (same method, opponent prevented from bidding):

| power | R1 | R2 | R3 | R4 | R5 |
|---|---|---|---|---|---|
| FORESIGHT | +0.78 | +0.49 | +0.71 | +0.26 | +0.04 |
| TRICK_ROOM | +0.37 | +0.49 | +0.04 | +0.03 | +0.03 |
| SUBSTITUTE | +1.24 | +0.93 | +0.60 | +0.01 | -0.06 |
| STEALTH_ROCK | +0.25 | +0.11 | 0.00 | 0.00 | -- |

**The two disagree in SHAPE, not just scale** -- SUBSTITUTE rises in self-play
and falls against the panel. Power value is genuinely opponent-dependent:
STEALTH_ROCK is worth 0 to us because WE rarely reach a forced fill, but that
is a fact about our own play, not about the power. Neither table is "the"
answer. Shipped the self-play table with SHADE re-swept to 0.30, because it
measured better against the STRONG half of the panel, the board recons and the
liars; the panel table won only against weak opponents.

### TRANSFORM is worth zero and we should never touch it

| rule | R1 | R2 | R3 |
|---|---|---|---|
| never fire | **0.00** | **0.00** | **0.00** |
| always fire | 0.00 | 0.00 | 0.00 |
| fire when flat (old rule) | -0.26 | -1.28 | +0.10 |
| fire on relative hand strength | -0.26 | -1.83 | -1.32 |

The swap is EV-neutral by symmetry, so every CONDITIONAL rule only adds
variance. Tested and rejected a swap-aware belief reset (detect the hand
change, treat their new revealed sum as our old one, which we knew exactly):
it moved R2 from -1.28 to -1.16. Not the mechanism.

## Dead ends from this round (do not re-run)

- **Confidence-scaled ride bar.** Posterior sd runs 6.0 (R1 blind) to 0.0 (R5
  with a same-round read), and our bar ignores it -- but every blend of
  `a*sd + b*spread` lost to pure `0.8*spread`. The spread ALREADY proxies
  confidence: the floors narrow 4,4,3,3,2 exactly as certainty rises, so
  adding sd double-counts.
- **Adverse-selection correction.** Shading the estimate against the side we
  are trading beat v2 head-to-head by +0.50 and LOST on the honest panel and
  the board recons. It exploited v2 specifically. A clean example of why
  head-to-head alone is not sufficient evidence.
- **Parity on counters / on the forced-fill price.** Both negative. Only the
  opening quote is scored against a lattice-computed probability.
