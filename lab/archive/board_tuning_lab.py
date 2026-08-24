"""board_tuning_lab.py — Dedicated lab targeting the 10 leaderboard opponents.

Targeting the bottlenecks identified from the live leaderboard score (+121.98):
1. Bot 10 (Foresight Deflation): Quote compression detection & anti-bias filter.
2. Bot 8 (Forced Fill Engineer) & Bot 9 (Min Counter Squeeze): Strategic counter steering on Turns 2-5.
3. Bot 6 (Shift Power Camper): Shift-aware counter positioning and anti-camp trade acceptance.
4. Dynamic auction escalation when opponent bids heavily on FORESIGHT.
"""

from __future__ import annotations
import os, sys, statistics
from math import erf, exp, sqrt, comb

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "quantstorm-ps"))
LAB = os.path.dirname(os.path.abspath(__file__))
if REPO not in sys.path: sys.path.insert(0, REPO)
if LAB not in sys.path: sys.path.insert(0, LAB)

from engine import play_match
from game_config import GameConfig
from arena import load_bot, duel, SEEDS, N_DEALS
from opponents import PANEL, LIARS
import board_bots as BB

CONFIG = GameConfig()
BASE_PATH = os.path.join(LAB, "bot", "qs_bot.py")
BaseBotCls = load_bot(BASE_PATH, "v9_base")

def _norm_cdf(x): return 0.5 * (1.0 + erf(x / 1.4142135623730951))
def _norm_pdf(x): return exp(-0.5 * x * x) / 2.5066282746310002
def _opt_sub(mu, sigma, cap=2.0):
    if sigma <= 1e-4: return max(mu, -cap)
    z = (mu + cap) / sigma
    return mu * _norm_cdf(z) - cap * (1.0 - _norm_cdf(z)) + sigma * _norm_pdf(z)
def _opt_opp_sub(mu, sigma, cap=2.0):
    return -_opt_sub(-mu, sigma, cap)

def make_variant(suffix, overrides):
    class V(BaseBotCls): pass
    V.name = f"QS_{suffix}"
    for k, fn in overrides.items():
        setattr(V, k, fn)
    return V


# ═════════════════════════════════════════════════════════════════
# IDEA 1: STRATEGIC COUNTER STEERING (Aggro-style counter)
# Instead of centering counter on v, steer it to maximize our option value
# ═════════════════════════════════════════════════════════════════

def _respond_steer_counters(self, obs, quote, turn):
    self._refresh(obs)
    bid, ask = quote
    if turn == 2 and not obs.is_maker and obs.round not in self.reads:
        self.reads[obs.round] = (bid + ask) / 2.0
        if abs(self.reads[obs.round]) > 4 * obs.round + 1.0:
            self.p_honest *= 0.1
    v = self._est(obs)
    fee = self.config.FORCED_FILL_FEE
    shift = self._shift(obs)
    sigma = sqrt(max(1, self._unseen(obs)))
    floor = obs.final_cap

    if turn >= obs.n_turns:
        force_px = max((bid + ask) // 2, ask - floor // 2) + shift
        sub_mine = "SUBSTITUTE" in obs.powers_mine
        sub_theirs = "SUBSTITUTE" in obs.powers_theirs
        if sub_mine:
            opt_buy = _opt_sub(v - ask, sigma)
            opt_sell = _opt_sub(bid - v, sigma)
            opt_force = _opt_sub(force_px - v, sigma) - fee
        elif sub_theirs:
            opt_buy = _opt_opp_sub(v - ask, sigma)
            opt_sell = _opt_opp_sub(bid - v, sigma)
            opt_force = _opt_opp_sub(force_px - v, sigma) - fee
        else:
            opt_buy = v - ask
            opt_sell = bid - v
            opt_force = force_px - v - fee
        return max([(opt_buy, "ACCEPT_BUY"), (opt_sell, "ACCEPT_SELL"),
                    (opt_force, ("COUNTER", ask, ask))], key=lambda o: o[0])[1]

    raw_buy = v - ask
    raw_sell = bid - v
    if "SUBSTITUTE" in obs.powers_mine:
        ev_buy = _opt_sub(raw_buy, sigma); ev_sell = _opt_sub(raw_sell, sigma)
    elif "SUBSTITUTE" in obs.powers_theirs:
        ev_buy = _opt_opp_sub(raw_buy, sigma); ev_sell = _opt_opp_sub(raw_sell, sigma)
    else:
        ev_buy = raw_buy; ev_sell = raw_sell

    info_count = len(obs.foresight) + len(self.reads)
    if self.p_honest < 0.3: ride = 0.85
    elif info_count > 4: ride = 0.55
    elif info_count > 2: ride = 0.60
    else: ride = 0.70
    if self.p_forcer > 0.5: ride += 0.10

    bar = ride * (ask - bid)
    if shift > 0 and not obs.is_maker:
        bar = max(bar, float(shift - 2.0))

    if ev_buy > bar and ev_buy >= ev_sell: return "ACCEPT_BUY"
    if ev_sell > bar: return "ACCEPT_SELL"

    w = max(floor, (ask - bid) - self.config.MIN_REDUCTION)
    
    # STRATEGIC COUNTER STEERING:
    # If v is far from midpoint, skew counter toward our edge rather than midpoint
    mid = (bid + ask) / 2.0
    if v < mid - 0.5:
        # We think S is low. As eventual seller (short), higher fill is better.
        # Push the ask as high as possible:
        c = max(bid, ask - w)
    elif v > mid + 0.5:
        # We think S is high. Push the bid as low as possible:
        c = bid
    else:
        c = max(bid, min(int(round(v)), ask - w))
        
    return ("COUNTER", c, c + w)

SteerCountersBot = make_variant("SteerCounters", {"respond": _respond_steer_counters})


# ═════════════════════════════════════════════════════════════════
# IDEA 2: ANTI-COMPRESSION DE-BIASING
# Detect if opponent quote midpoint is abnormally compressed (|mid| << 2*r)
# ═════════════════════════════════════════════════════════════════

def _their_k_debias(self, obs):
    parts = []
    n = len(obs.foresight)
    if n:
        parts.append((float(sum(obs.foresight)), float(4 * obs.round - n)))

    if self.reads and self.p_honest > 0.3:
        r0 = max(self.reads)
        raw_mid = self.reads[r0]
        # If the read is consistently small (|mid| <= 1.0) while our own |k_mine| is large,
        # opponent might be compressing toward 0.
        # Scale up the read if it looks compressed:
        est_val = raw_mid
        noise = 2.0 / max(0.2, self.p_honest)
        parts.append((est_val, 4.0 * (obs.round - r0) + noise))

    if not parts:
        return None
    for est, var in parts:
        if var <= 0.0:
            return est, 0.0
    wsum = sum(1.0 / var for _, var in parts)
    est = sum(e / var for e, var in parts) / wsum
    return est, 1.0 / wsum

DebiasBot = make_variant("Debias", {"_their_k": _their_k_debias})


# ═════════════════════════════════════════════════════════════════
# IDEA 3: FORESIGHT COMPETITIVE BIDDING
# Value FORESIGHT higher in rounds 1-3 to prevent deflation bots from monopolizing it
# ═════════════════════════════════════════════════════════════════

def _power_value_higher_foresight(self, obs, name):
    r = obs.round
    if name == "FORESIGHT":
        m = min(16, 4 * r)
        # Higher baseline valuation: 0.95 * sqrt(m)
        return 0.95 * sqrt(m) + (0.8 if obs.is_maker else 0.3)
    elif name == "SUBSTITUTE":
        return 0.55 * (r + 1.0)
    elif name == "TRICK_ROOM":
        return 0.8 / r
    elif name == "STEALTH_ROCK":
        return 2.0 * 0.28 * (5 - r + 1)
    return 0.0

HigherForesightBot = make_variant("HighForesight", {"_power_value": _power_value_higher_foresight})


# ═════════════════════════════════════════════════════════════════
# IDEA 4: COMBINED BOARD SPECIALIST
# ═════════════════════════════════════════════════════════════════

CombinedBoardBot = make_variant("CombinedBoard", {
    "respond": _respond_steer_counters,
    "_power_value": _power_value_higher_foresight,
})


def eval_on_board(label, cls, seeds=SEEDS, n_deals=40):
    # Score on board reconstructions
    b_scores = [(name, duel(cls, opp, seeds, n_deals).mean) for name, opp in BB.BOARD]
    b_mean = statistics.fmean([s for _, s in b_scores])
    worst_b, worst_bv = min(b_scores, key=lambda x: x[1])

    # Score on honest panel
    p_scores = [(name, duel(cls, opp, seeds, n_deals).mean) for name, opp in PANEL]
    p_mean = statistics.fmean([s for _, s in p_scores])

    # Score on liars
    l_scores = [(name, duel(cls, opp, seeds, n_deals).mean) for name, opp in LIARS]
    l_mean = statistics.fmean([s for _, s in l_scores])

    # Head to head vs Base v9
    h2h = duel(cls, BaseBotCls, seeds, n_deals)

    print(f"  {label:<25s} | H2H: {h2h.mean:>+5.2f} | Board: {b_mean*20:>+6.1f} ({b_mean:>+5.2f}/d) | Honest: {p_mean*20:>+6.1f} | Liar: {l_mean*20:>+6.1f} | Worst Board: {worst_b} ({worst_bv*20:+.1f})")


def main():
    print()
    print("=" * 115)
    print("BOARD BOT TARGETING LAB: EXPERIMENTS AGAINST LEADERBOARD BOT RECONSTRUCTIONS")
    print("=" * 115)
    print(f"  Config: {len(SEEDS)} seeds x {40 * 2} deals each")
    print()

    eval_on_board("Base v9 (current)", BaseBotCls)
    eval_on_board("1. Steer Counters", SteerCountersBot)
    eval_on_board("2. Higher Foresight", HigherForesightBot)
    eval_on_board("3. Combined Board", CombinedBoardBot)

    print()
    print("=" * 115)


if __name__ == "__main__":
    main()
