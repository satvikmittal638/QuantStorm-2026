"""parameter_tuner.py — Comprehensive parameter grid search around v9 architecture.

Sweeps the key game parameters:
1. SHADE (auction shading factor): 0.26, 0.30, 0.33, 0.36
2. SR_RATE (Stealth Rock valuation multiplier): 0.18, 0.22, 0.25, 0.30
3. BASE_RIDE (Default negotiation ride fraction): 0.60, 0.65, 0.70, 0.75
4. FS_SCALE (Foresight multiplier): 0.65, 0.75, 0.85
5. INVENTORY_PENALTY (TE cushion maker penalty): 0.01, 0.02, 0.03
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
V9BotCls = load_bot(V9_PATH, "v9_base_tuner")

def _norm_cdf(x): return 0.5 * (1.0 + erf(x / 1.4142135623730951))
def _norm_pdf(x): return exp(-0.5 * x * x) / 2.5066282746310002
def _opt_sub(mu, sigma, cap=2.0):
    if sigma <= 1e-4: return max(mu, -cap)
    z = (mu + cap) / sigma
    return mu * _norm_cdf(z) - cap * (1.0 - _norm_cdf(z)) + sigma * _norm_pdf(z)
def _opt_opp_sub(mu, sigma, cap=2.0):
    return -_opt_sub(-mu, sigma, cap)


def make_tuned_bot(
    shade=0.33,
    sr_rate=0.25,
    base_ride=0.70,
    fs_scale=0.75,
    inv_penalty=0.02,
    name="Tuned",
):
    class Tuned(V9BotCls):
        pass

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
            if lo % 2:
                lo += 1
            try:
                priced = cfg.straddle_prob(r, w)
            except Exception:
                continue
            true_p = self._cover(unseen, lo - v, lo - v + w)
            ev = (cfg.MAKER_OBLIGATION * (true_p - priced)
                  - cfg.WIDTH_PREMIUM * (w - floor))

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

        # Turn 6
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

            options = (
                (opt_buy, "ACCEPT_BUY"),
                (opt_sell, "ACCEPT_SELL"),
                (opt_force, ("COUNTER", ask, ask)),
            )
            return max(options, key=lambda o: o[0])[1]

        # Turns 2-5
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

        if ev_buy > bar and ev_buy >= ev_sell:
            return "ACCEPT_BUY"
        if ev_sell > bar:
            return "ACCEPT_SELL"

        w = max(floor, (ask - bid) - self.config.MIN_REDUCTION)
        c = max(bid, min(int(round(v)), ask - w))
        return ("COUNTER", c, c + w)

    def _bid(self, obs, offered):
        budget = int(obs.te_mine)
        if not offered or budget <= 0:
            return {}
        if obs.te_theirs <= 0:
            return {offered[0]: 1}

        curr_shade = shade
        if self.p_passive > 0.6:
            curr_shade = shade * 0.65
        elif self.p_forcer > 0.6:
            curr_shade = min(0.45, shade * 1.15)

        wanted: list[tuple[float, str, int]] = []
        for n in offered:
            v = self._power_value(obs, n)
            if v <= 0.0:
                continue
            amount = int(v / self.config.TE_SALVAGE * curr_shade)
            amount = min(amount, int(obs.te_theirs) + 1)
            if amount > 0:
                wanted.append((v, n, amount))

        out: dict[str, int] = {}
        for _, n, amount in sorted(wanted, key=lambda t: -t[0]):
            take = min(amount, budget)
            if take <= 0:
                break
            out[n] = take
            budget -= take
        return out

    Tuned._power_value = _power_val
    Tuned.quote = _quote
    Tuned.respond = _respond
    Tuned.bid = _bid
    return Tuned


def evaluate(label, bot_cls, seeds=SEEDS, n_deals=30):
    b_scores = [duel(bot_cls, opp, seeds, n_deals).mean for _, opp in BB.BOARD]
    b_mean = statistics.fmean(b_scores)
    p_scores = [duel(bot_cls, opp, seeds, n_deals).mean for _, opp in PANEL]
    p_mean = statistics.fmean(p_scores)
    l_scores = [duel(bot_cls, opp, seeds, n_deals).mean for _, opp in LIARS]
    l_mean = statistics.fmean(l_scores)
    h2h = duel(bot_cls, V9BotCls, seeds, n_deals).mean

    # Weighted combined tournament fitness metric
    fitness = 0.50 * (b_mean * 20) + 0.35 * (p_mean * 20) + 0.15 * (l_mean * 20)
    print(f"  {label:<32s} | H2H: {h2h:>+5.2f} | Board: {b_mean*20:>+6.1f} | Honest: {p_mean*20:>+6.1f} | Liar: {l_mean*20:>+6.1f} | FIT: {fitness:>+6.1f}")
    return fitness, b_mean, p_mean, l_mean


def main():
    print()
    print("=" * 115)
    print("PARAMETER SWEEP AROUND v9 ARCHITECTURE")
    print("=" * 115)

    print("\n  1. Base v9 Reference")
    evaluate("v9 (default constants)", V9BotCls)

    print("\n  2. Base Ride Sweeps (base_ride in [0.60, 0.65, 0.70, 0.75])")
    for r in (0.60, 0.65, 0.70, 0.75):
        evaluate(f"base_ride = {r:.2f}", make_tuned_bot(base_ride=r))

    print("\n  3. Stealth Rock Valuation Sweeps (sr_rate in [0.18, 0.22, 0.25, 0.30])")
    for sr in (0.18, 0.22, 0.25, 0.30):
        evaluate(f"sr_rate = {sr:.2f}", make_tuned_bot(sr_rate=sr))

    print("\n  4. Auction Shade Sweeps (shade in [0.26, 0.30, 0.33, 0.36])")
    for sh in (0.26, 0.30, 0.33, 0.36):
        evaluate(f"shade = {sh:.2f}", make_tuned_bot(shade=sh))

    print("\n  5. Foresight Scaling Sweeps (fs_scale in [0.65, 0.75, 0.85])")
    for fs in (0.65, 0.75, 0.85):
        evaluate(f"fs_scale = {fs:.2f}", make_tuned_bot(fs_scale=fs))

    print("\n  6. Inventory Cushion Penalty (inv_penalty in [0.01, 0.02, 0.03])")
    for inv in (0.01, 0.02, 0.03):
        evaluate(f"inv_penalty = {inv:.2f}", make_tuned_bot(inv_penalty=inv))

    print("\n" + "=" * 115)


if __name__ == "__main__":
    main()
