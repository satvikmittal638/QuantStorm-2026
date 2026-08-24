"""test_v10_candidate.py — Comprehensive validation of v10 candidate.
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
from arena import load_bot, duel, SEEDS, N_DEALS, report, selfplay_control
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


def _refresh_v10(self, obs):
    # 1. Update from Auction Tape
    if obs.auction_log:
        opp_wins = [e for e in obs.auction_log if e["seat"] != self.seat]
        if opp_wins:
            last_win = opp_wins[-1]
            if last_win["cost"] >= 5:
                self.p_passive *= 0.2
                self.p_forcer = min(1.0, self.p_forcer + 0.3)
            elif last_win["cost"] == 0:
                self.p_passive = min(1.0, self.p_passive + 0.3)

    # 2. Update from Contracts and Physical Drift Feasibility
    for c in obs.contracts:
        if c.maker_seat != self.seat and c.round not in self.reads:
            mid = (c.open_bid + c.open_ask) / 2.0
            r = c.round
            if abs(mid) > 4 * r + 0.5:
                self.p_honest = 0.0
            for prev_r, prev_mid in self.reads.items():
                if abs(mid - prev_mid) > 4 * abs(r - prev_r) + 0.5:
                    self.p_honest = 0.0
            self.reads[r] = mid

    # 3. Precision FORESIGHT Cross-Validation
    if obs.foresight and self.reads and obs.round in self.reads:
        f_sum = float(sum(obs.foresight))
        q_mid = self.reads[obs.round]
        n_seen = len(obs.foresight)
        total_their_revealed = 4 * obs.round

        if n_seen == total_their_revealed:
            err = abs(q_mid - f_sum)
            if err > 0.6:
                self.p_honest = 0.0
            else:
                self.p_honest = min(1.0, self.p_honest + 0.3)
        else:
            err = abs(q_mid - f_sum)
            if err > 4.0:
                self.p_honest = 0.0
            elif err < 1.0:
                self.p_honest = min(1.0, self.p_honest + 0.2)


def _respond_v10(self, obs, quote, turn: int):
    self._refresh(obs)
    bid, ask = quote

    if turn == 2 and not obs.is_maker and obs.round not in self.reads:
        mid = (bid + ask) / 2.0
        self.reads[obs.round] = mid
        if abs(mid) > 4 * obs.round + 0.5:
            self.p_honest = 0.0

    v = self._est(obs)
    fee = self.config.FORCED_FILL_FEE
    shift = self._shift(obs)
    sigma = sqrt(max(1, self._unseen(obs)))
    floor = obs.final_cap

    # -- Turn 6 (Final turn: Taker only) --
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

    # -- Turns 2 to 5 --
    raw_buy = v - ask
    raw_sell = bid - v
    if "SUBSTITUTE" in obs.powers_mine:
        ev_buy = _opt_sub(raw_buy, sigma)
        ev_sell = _opt_sub(raw_sell, sigma)
    elif "SUBSTITUTE" in obs.powers_theirs:
        ev_buy = _opt_opp_sub(raw_buy, sigma)
        ev_sell = _opt_opp_sub(raw_sell, sigma)
    else:
        ev_buy = raw_buy
        ev_sell = raw_sell

    info_count = len(obs.foresight) + (len(self.reads) if self.p_honest > 0.4 else 0)
    if self.p_honest < 0.3:
        ride = 0.85
    elif info_count > 4:
        ride = 0.55
    elif info_count > 2:
        ride = 0.60
    else:
        ride = 0.70
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
    mid = (bid + ask) / 2.0
    if v < mid - 0.5:
        c = max(bid, ask - w)
    elif v > mid + 0.5:
        c = bid
    else:
        c = max(bid, min(int(round(v)), ask - w))
    return ("COUNTER", c, c + w)


def _power_value_v10(self, obs, name: str) -> float:
    r = obs.round
    if name == "FORESIGHT":
        m = min(16, 4 * r)
        return 0.80 * sqrt(m) + (0.5 if obs.is_maker else 0.0)
    elif name == "SUBSTITUTE":
        sigma = sqrt(max(1, self._unseen(obs)))
        z = 2.0 / sigma
        bachelier = sigma * _norm_pdf(z) - 2.0 * (1.0 - _norm_cdf(z))
        return 0.85 * bachelier + 0.30
    elif name == "TRICK_ROOM":
        return 0.6 / r
    elif name == "STEALTH_ROCK":
        remaining = 5 - r + 1
        return 2.0 * 0.25 * remaining
    return 0.0


V10Candidate = make_variant("V10Candidate", {
    "_refresh": _refresh_v10,
    "respond": _respond_v10,
    "_power_value": _power_value_v10,
})


def main():
    print()
    print("=" * 115)
    print("VALIDATING V10 CANDIDATE vs V9 BASE")
    print("=" * 115)

    selfplay_control(V10Candidate)
    
    h2h = duel(V10Candidate, BaseBotCls, SEEDS, 60)
    print(f"\n  H2H (V10 vs V9): {h2h.mean:>+6.2f} +/- {h2h.stderr:4.2f} ticks/deal ({h2h.mean * 20:>+6.1f} /match)")

    b_scores = [(name, duel(V10Candidate, opp, SEEDS, 60).mean) for name, opp in BB.BOARD]
    b_mean = statistics.fmean([s for _, s in b_scores])
    print(f"  BOARD MEAN:      {b_mean:>+6.2f} ticks/deal ({b_mean * 20:>+6.1f} /match)")

    p_scores = [(name, duel(V10Candidate, opp, SEEDS, 60).mean) for name, opp in PANEL]
    p_mean = statistics.fmean([s for _, s in p_scores])
    print(f"  HONEST PANEL:    {p_mean:>+6.2f} ticks/deal ({p_mean * 20:>+6.1f} /match)")

    l_scores = [(name, duel(V10Candidate, opp, SEEDS, 60).mean) for name, opp in LIARS]
    l_mean = statistics.fmean([s for _, s in l_scores])
    print(f"  LIARS:           {l_mean:>+6.2f} ticks/deal ({l_mean * 20:>+6.1f} /match)")

    print("\n" + "=" * 115)


if __name__ == "__main__":
    main()
