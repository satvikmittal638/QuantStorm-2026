"""strategy_lab2.py — Phase 2: Targeted ablation of winning hypotheses.

Findings from Phase 1:
  H2 (STEALTH_ROCK):  +0.83 panel but -0.34 H2H, -0.58 liar delta
  H5 (Low Ride 0.65): +0.19 panel, +0.68 liar delta  
  H6 (Hedge):         +0.12 panel, +0.74 liar delta

Phase 2 explores:
  A. STEALTH_ROCK valuation sweep (find optimal force_rate parameter)
  B. Ride hurdle sweep (0.55, 0.60, 0.65, 0.70, 0.75)
  C. Combined STEALTH_ROCK + Low Ride
  D. Adaptive ride (lower when we have information edge)
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

CONFIG = GameConfig()
BASE_PATH = os.path.join(LAB, "bot", "qs_bot.py")
BaseBotCls = load_bot(BASE_PATH, "base_ref2")

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
# A. STEALTH_ROCK valuation sweep
# ═════════════════════════════════════════════════════════════════

def make_sr_bot(force_rate):
    def _pv(self, obs, name):
        r = obs.round
        if name == "FORESIGHT":
            m = min(16, 4 * r)
            return 0.75 * sqrt(m) + (0.5 if obs.is_maker else 0.0)
        elif name == "SUBSTITUTE":
            return 0.5 * (r + 1.0)
        elif name == "TRICK_ROOM":
            return 0.6 / r
        elif name == "STEALTH_ROCK":
            return 2.0 * force_rate * (5 - r + 1)
        return 0.0
    return make_variant(f"SR_{force_rate:.2f}", {"_power_value": _pv})


# ═════════════════════════════════════════════════════════════════
# B. Ride hurdle sweep
# ═════════════════════════════════════════════════════════════════

def make_ride_bot(ride_val):
    def _respond(self, obs, quote, turn):
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

        ride = ride_val
        if self.p_forcer > 0.5: ride += 0.05
        bar = ride * (ask - bid)
        if shift > 0 and not obs.is_maker: bar = max(bar, float(shift - 2.0))
        if ev_buy > bar and ev_buy >= ev_sell: return "ACCEPT_BUY"
        if ev_sell > bar: return "ACCEPT_SELL"
        w = max(floor, (ask - bid) - self.config.MIN_REDUCTION)
        c = max(bid, min(int(round(v)), ask - w))
        return ("COUNTER", c, c + w)
    return make_variant(f"Ride_{ride_val:.2f}", {"respond": _respond})


# ═════════════════════════════════════════════════════════════════
# C. Combined: Best SR + Best Ride
# ═════════════════════════════════════════════════════════════════

def make_combined(sr_rate, ride_val):
    def _pv(self, obs, name):
        r = obs.round
        if name == "FORESIGHT":
            m = min(16, 4 * r)
            return 0.75 * sqrt(m) + (0.5 if obs.is_maker else 0.0)
        elif name == "SUBSTITUTE":
            return 0.5 * (r + 1.0)
        elif name == "TRICK_ROOM":
            return 0.6 / r
        elif name == "STEALTH_ROCK":
            return 2.0 * sr_rate * (5 - r + 1)
        return 0.0

    def _respond(self, obs, quote, turn):
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
            if "SUBSTITUTE" in obs.powers_mine:
                opt_buy = _opt_sub(v - ask, sigma)
                opt_sell = _opt_sub(bid - v, sigma)
                opt_force = _opt_sub(force_px - v, sigma) - fee
            elif "SUBSTITUTE" in obs.powers_theirs:
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

        ride = ride_val
        if self.p_forcer > 0.5: ride += 0.05
        bar = ride * (ask - bid)
        if shift > 0 and not obs.is_maker: bar = max(bar, float(shift - 2.0))
        if ev_buy > bar and ev_buy >= ev_sell: return "ACCEPT_BUY"
        if ev_sell > bar: return "ACCEPT_SELL"
        w = max(floor, (ask - bid) - self.config.MIN_REDUCTION)
        c = max(bid, min(int(round(v)), ask - w))
        return ("COUNTER", c, c + w)

    return make_variant(f"SR{sr_rate:.2f}_R{ride_val:.2f}", {
        "_power_value": _pv, "respond": _respond
    })


# ═════════════════════════════════════════════════════════════════
# D. Adaptive Ride (information-dependent)
# ═════════════════════════════════════════════════════════════════

def _respond_adaptive_ride(self, obs, quote, turn):
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
        if "SUBSTITUTE" in obs.powers_mine:
            opt_buy = _opt_sub(v - ask, sigma)
            opt_sell = _opt_sub(bid - v, sigma)
            opt_force = _opt_sub(force_px - v, sigma) - fee
        elif "SUBSTITUTE" in obs.powers_theirs:
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

    # Adaptive ride: lower when we have more information (more foresight/reads)
    base_ride = 0.70
    info_count = len(obs.foresight) + len(self.reads)
    if info_count > 4:
        base_ride = 0.55  # We have good information, trust our estimates
    elif info_count > 2:
        base_ride = 0.60
    if self.p_forcer > 0.5:
        base_ride += 0.10
    if self.p_honest < 0.3:
        base_ride = 0.85  # Opponent is adversarial, be cautious
    
    bar = base_ride * (ask - bid)
    if shift > 0 and not obs.is_maker:
        bar = max(bar, float(shift - 2.0))
    if ev_buy > bar and ev_buy >= ev_sell: return "ACCEPT_BUY"
    if ev_sell > bar: return "ACCEPT_SELL"
    w = max(floor, (ask - bid) - self.config.MIN_REDUCTION)
    c = max(bid, min(int(round(v)), ask - w))
    return ("COUNTER", c, c + w)


def _pv_sr_adaptive(self, obs, name):
    r = obs.round
    if name == "FORESIGHT":
        m = min(16, 4 * r)
        return 0.75 * sqrt(m) + (0.5 if obs.is_maker else 0.0)
    elif name == "SUBSTITUTE":
        return 0.5 * (r + 1.0)
    elif name == "TRICK_ROOM":
        return 0.6 / r
    elif name == "STEALTH_ROCK":
        return 2.0 * 0.35 * (5 - r + 1)
    return 0.0


AdaptiveRide = make_variant("AdaptRide", {
    "respond": _respond_adaptive_ride,
    "_power_value": _pv_sr_adaptive,
})


def eval_bot(label, cls, seeds=SEEDS, n_deals=40):
    h2h = duel(cls, BaseBotCls, seeds, n_deals)
    ps = [(n, duel(cls, o, seeds, n_deals).mean) for n, o in PANEL]
    p_mean = statistics.fmean([s for _, s in ps])
    worst_n, worst_v = min(ps, key=lambda x: x[1])
    ls = [duel(cls, o, seeds, n_deals).mean for _, o in LIARS]
    l_mean = statistics.fmean(ls)
    print(f"  {label:<35s} | H2H: {h2h.mean:>+6.2f} | Panel: {p_mean:>+5.2f}"
          f" | Liar: {l_mean:>+5.2f} | Worst: {worst_n} ({worst_v:+.2f})")


if __name__ == "__main__":
    print("\n" + "=" * 105)
    print("PHASE 2: TARGETED ABLATION OF WINNING HYPOTHESES")
    print("=" * 105)

    print("\n  --- A. STEALTH_ROCK Force-Rate Sweep ---")
    eval_bot("Control (no SR bid)", BaseBotCls)
    for fr in (0.25, 0.35, 0.45, 0.55):
        eval_bot(f"SR force_rate={fr:.2f}", make_sr_bot(fr))

    print("\n  --- B. Ride Hurdle Sweep ---")
    for rv in (0.55, 0.60, 0.65, 0.70, 0.75, 0.80):
        eval_bot(f"Ride={rv:.2f}", make_ride_bot(rv))

    print("\n  --- C. Combined: SR + Ride ---")
    for sr, rv in [(0.35, 0.65), (0.35, 0.70), (0.45, 0.65), (0.45, 0.70)]:
        eval_bot(f"SR={sr:.2f} + Ride={rv:.2f}", make_combined(sr, rv))

    print("\n  --- D. Adaptive Ride (info-dependent) ---")
    eval_bot("Adaptive Ride + SR", AdaptiveRide)

    print("\n" + "=" * 105)
