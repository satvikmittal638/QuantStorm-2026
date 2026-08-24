"""fine_tuning_lab.py — Fine-grained joint parameter optimization.
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
V9BotCls = load_bot(V9_PATH, "v9_fine_ref")

def _norm_cdf(x): return 0.5 * (1.0 + erf(x / 1.4142135623730951))
def _norm_pdf(x): return exp(-0.5 * x * x) / 2.5066282746310002
def _opt_sub(mu, sigma, cap=2.0):
    if sigma <= 1e-4: return max(mu, -cap)
    z = (mu + cap) / sigma
    return mu * _norm_cdf(z) - cap * (1.0 - _norm_cdf(z)) + sigma * _norm_pdf(z)
def _opt_opp_sub(mu, sigma, cap=2.0):
    return -_opt_sub(-mu, sigma, cap)


def make_tuned_bot(shade=0.31, sr_rate=0.24, base_ride=0.66, fs_scale=0.70, inv_penalty=0.02, name="Fine"):
    class Tuned(V9BotCls): pass
    Tuned.name = f"QS_{name}"

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

    def _quote(self, obs):
        self._refresh(obs)
        cfg = self.config
        v = int(round(self._est(obs)))
        r, floor, cap = obs.round, obs.final_cap, obs.spread_cap
        unseen = self._unseen(obs)
        te_inventory_cushion = obs.te_mine - obs.te_theirs
        best_ev, best_lo, best_w = None, v - floor // 2, floor
        for w in range(floor, cap + 1):
            lo = v - w // 2
            if lo % 2: lo += 1
            try: priced = cfg.straddle_prob(r, w)
            except Exception: continue
            true_p = self._cover(unseen, lo - v, lo - v + w)
            ev = (cfg.MAKER_OBLIGATION * (true_p - priced) - cfg.WIDTH_PREMIUM * (w - floor))
            if te_inventory_cushion < 0:
                ev -= inv_penalty * abs(te_inventory_cushion) * (w - floor)
            if best_ev is None or ev > best_ev:
                best_ev, best_lo, best_w = ev, lo, w
        return (best_lo, best_lo + best_w)

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
        if self.p_passive > 0.6: curr_shade = shade * 0.65
        elif self.p_forcer > 0.6: curr_shade = min(0.45, shade * 1.15)
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

    Tuned._power_value = _power_val
    Tuned.quote = _quote
    Tuned.respond = _respond
    Tuned.bid = _bid
    return Tuned


def main():
    print()
    print("=" * 115)
    print("FINE-GRAINED PARAMETER OPTIMIZATION")
    print("=" * 115)

    candidates = [
        ("v9 Baseline", V9BotCls),
        ("Candidate A (shade=0.30, fs=0.70, sr=0.24, ride=0.65)", make_tuned_bot(shade=0.30, fs_scale=0.70, sr_rate=0.24, base_ride=0.65)),
        ("Candidate B (shade=0.31, fs=0.68, sr=0.22, ride=0.65)", make_tuned_bot(shade=0.31, fs_scale=0.68, sr_rate=0.22, base_ride=0.65)),
        ("Candidate C (shade=0.32, fs=0.72, sr=0.25, ride=0.68)", make_tuned_bot(shade=0.32, fs_scale=0.72, sr_rate=0.25, base_ride=0.68)),
    ]

    for label, cls in candidates:
        b_scores = [duel(cls, opp, SEEDS, 40).mean for _, opp in BB.BOARD]
        b_mean = statistics.fmean(b_scores)
        p_scores = [duel(cls, opp, SEEDS, 40).mean for _, opp in PANEL]
        p_mean = statistics.fmean(p_scores)
        l_scores = [duel(cls, opp, SEEDS, 40).mean for _, opp in LIARS]
        l_mean = statistics.fmean(l_scores)
        h2h = duel(cls, V9BotCls, SEEDS, 40).mean
        fit = 0.50 * (b_mean * 20) + 0.35 * (p_mean * 20) + 0.15 * (l_mean * 20)
        print(f"  {label:<55s} | H2H: {h2h:>+5.2f} | Board: {b_mean*20:>+6.1f} | Honest: {p_mean*20:>+6.1f} | Liar: {l_mean*20:>+6.1f} | FIT: {fit:>+6.1f}")

    print("=" * 115)


if __name__ == "__main__":
    main()
