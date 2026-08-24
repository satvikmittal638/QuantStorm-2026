"""test_hybrid_peak.py — Test hybrid restoring auction aggression while keeping negotiation edge.
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
V9_PATH = os.path.join(LAB, "versions", "v9_adaptive_engine.py")
V9BotCls = load_bot(V9_PATH, "v9_peak_ref")

def _norm_cdf(x): return 0.5 * (1.0 + erf(x / 1.4142135623730951))
def _norm_pdf(x): return exp(-0.5 * x * x) / 2.5066282746310002
def _opt_sub(mu, sigma, cap=2.0):
    if sigma <= 1e-4: return max(mu, -cap)
    z = (mu + cap) / sigma
    return mu * _norm_cdf(z) - cap * (1.0 - _norm_cdf(z)) + sigma * _norm_pdf(z)
def _opt_opp_sub(mu, sigma, cap=2.0):
    return -_opt_sub(-mu, sigma, cap)


def make_hybrid_bot(shade=0.33, sr_rate=0.25, fs_scale=0.75, base_ride=0.65):
    class Hybrid(V9BotCls): pass

    def _power_val(self, obs, p_name: str) -> float:
        r = obs.round
        if p_name == "FORESIGHT":
            m = min(16, 4 * r)
            return fs_scale * sqrt(m) + (0.5 if obs.is_maker else 0.0)
        elif p_name == "SUBSTITUTE":
            return 0.5 * (r + 1.0)
        elif p_name == "TRICK_ROOM":
            return 0.6 / r
        elif p_name == "STEALTH_ROCK":
            remaining = 5 - r + 1
            return 2.0 * sr_rate * remaining
        return 0.0

    def _respond(self, obs, quote, turn: int):
        self._refresh(obs)
        bid, ask = quote
        if turn == 2 and not obs.is_maker and obs.round not in self.reads:
            mid = (bid + ask) / 2.0
            self.reads[obs.round] = mid
            if abs(mid) > 4 * obs.round + 1.0:
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

        info_count = len(obs.foresight) + len(self.reads)
        if self.p_honest < 0.3:
            ride = 0.85
        elif info_count > 4:
            ride = base_ride - 0.15
        elif info_count > 2:
            ride = base_ride - 0.10
        else:
            ride = base_ride

        if self.p_forcer > 0.5:
            ride += 0.10

        bar = ride * (ask - bid)
        if shift > 0 and not obs.is_maker:
            bar = max(bar, float(shift - 2.0))

        if ev_buy > bar and ev_buy >= ev_sell: return "ACCEPT_BUY"
        if ev_sell > bar: return "ACCEPT_SELL"

        w = max(floor, (ask - bid) - self.config.MIN_REDUCTION)
        c = max(bid, min(int(round(v)), ask - w))
        return ("COUNTER", c, c + w)

    def _bid(self, obs, offered):
        budget = int(obs.te_mine)
        if not offered or budget <= 0: return {}
        if obs.te_theirs <= 0: return {offered[0]: 1}
        curr_shade = shade
        if self.p_passive > 0.6: curr_shade = 0.20
        elif self.p_forcer > 0.6: curr_shade = 0.35
        wanted: list[tuple[float, str, int]] = []
        for n in offered:
            v = self._power_value(obs, n)
            if v <= 0.0: continue
            amount = int(v / self.config.TE_SALVAGE * curr_shade)
            amount = min(amount, int(obs.te_theirs) + 1)
            if amount > 0: wanted.append((v, n, amount))
        out: dict[str, int] = {}
        for _, n, amount in sorted(wanted, key=lambda t: -t[0]):
            take = min(amount, budget)
            if take <= 0: break
            out[n] = take
            budget -= take
        return out

    Hybrid._power_value = _power_val
    Hybrid.respond = _respond
    Hybrid.bid = _bid
    return Hybrid


def main():
    print()
    print("=" * 115)
    print("HYBRID PEAK VALIDATION")
    print("=" * 115)

    candidates = [
        ("v9 Baseline (+121.98)", V9BotCls),
        ("Hybrid 1 (shade=0.33, sr=0.25, fs=0.75, ride=0.65)", make_hybrid_bot(shade=0.33, sr_rate=0.25, fs_scale=0.75, base_ride=0.65)),
        ("Hybrid 2 (shade=0.34, sr=0.26, fs=0.75, ride=0.65)", make_hybrid_bot(shade=0.34, sr_rate=0.26, fs_scale=0.75, base_ride=0.65)),
    ]

    for label, cls in candidates:
        b_scores = [(name, duel(cls, opp, SEEDS, 40).mean) for name, opp in BB.BOARD]
        b_mean = statistics.fmean([s for _, s in b_scores])
        p_scores = [(name, duel(cls, opp, SEEDS, 40).mean) for name, opp in PANEL]
        p_mean = statistics.fmean([s for _, s in p_scores])
        l_scores = [(name, duel(cls, opp, SEEDS, 40).mean) for name, opp in LIARS]
        l_mean = statistics.fmean([s for _, s in l_scores])
        h2h = duel(cls, V9BotCls, SEEDS, 40).mean
        print(f"\n  {label}")
        print(f"    H2H vs v9: {h2h:>+5.2f} | Board: {b_mean*20:>+6.1f} | Honest: {p_mean*20:>+6.1f} | Liar: {l_mean*20:>+6.1f}")
        for n, s in b_scores:
            print(f"      {n:<28s} {s*20:>+6.1f}")

    print("=" * 115)


if __name__ == "__main__":
    main()
