"""test_foresight_forensics.py — Precision forensics on quote honesty & compression.

Key theorem:
In rounds 1-4, FORESIGHT samples min(16, 4r) = 4r coins, which is 100% of the opponent's revealed hand.
Therefore, sum(foresight) is the EXACT revealed sum of the opponent.
Any honest Maker will have midpoint within 0.5 of this value.
If |q_mid - sum(foresight)| > 0.6, the opponent is mathematically guaranteed to be distorting their quote.

Furthermore, if the opponent is compressing (q_mid ≈ alpha * sum(foresight) with alpha < 1),
we can estimate alpha = q_mid / sum(foresight) and UN-COMPRESS it: k_est = q_mid / alpha!
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
# PRECISION FORENSICS BOT
# ═════════════════════════════════════════════════════════════════

def _refresh_precision(self, obs):
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

    # 2. Update from Contracts
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

    # 3. Exact FORESIGHT Cross-Validation
    if obs.foresight and self.reads and obs.round in self.reads:
        f_sum = float(sum(obs.foresight))
        q_mid = self.reads[obs.round]
        n_seen = len(obs.foresight)
        total_their_revealed = 4 * obs.round

        if n_seen == total_their_revealed:
            # We see 100% of their coins. f_sum is EXACT ground truth.
            err = abs(q_mid - f_sum)
            if err > 0.6:
                self.p_honest = 0.0  # Mathematically proven liar/compressor
            else:
                self.p_honest = 1.0  # Mathematically proven honest quoter
        else:
            # Round 5: we see 16/20 coins. 4 unknown coins have SD = 2.0
            err = abs(q_mid - f_sum)
            if err > 4.5:
                self.p_honest = 0.0
            elif err < 1.0:
                self.p_honest = min(1.0, self.p_honest + 0.3)


def _respond_steer_v10(self, obs, quote, turn):
    self._refresh(obs)
    bid, ask = quote
    if turn == 2 and not obs.is_maker and obs.round not in self.reads:
        self.reads[obs.round] = (bid + ask) / 2.0
        if abs(self.reads[obs.round]) > 4 * obs.round + 0.5:
            self.p_honest = 0.0
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

    info_count = len(obs.foresight) + (len(self.reads) if self.p_honest > 0.5 else 0)
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
    mid = (bid + ask) / 2.0
    if v < mid - 0.5:
        c = max(bid, ask - w)
    elif v > mid + 0.5:
        c = bid
    else:
        c = max(bid, min(int(round(v)), ask - w))
    return ("COUNTER", c, c + w)


PrecisionBot = make_variant("PrecisionForensics", {
    "_refresh": _refresh_precision,
    "respond": _respond_steer_v10,
})


def main():
    print()
    print("=" * 115)
    print("TESTING PRECISION FORENSICS + STRATEGIC COUNTER STEERING")
    print("=" * 115)

    for label, cls in [("Base v9", BaseBotCls), ("v10 Precision + Steer", PrecisionBot)]:
        h2h = duel(cls, BaseBotCls, SEEDS, 50)
        b_scores = [(name, duel(cls, opp, SEEDS, 50).mean) for name, opp in BB.BOARD]
        b_mean = statistics.fmean([s for _, s in b_scores])
        p_scores = [(name, duel(cls, opp, SEEDS, 50).mean) for name, opp in PANEL]
        p_mean = statistics.fmean([s for _, s in p_scores])
        l_scores = [(name, duel(cls, opp, SEEDS, 50).mean) for name, opp in LIARS]
        l_mean = statistics.fmean([s for _, s in l_scores])
        print(f"  {label:<25s} | H2H: {h2h.mean:>+5.2f} | Board: {b_mean*20:>+6.1f} ({b_mean:>+5.2f}/d) | Honest: {p_mean*20:>+6.1f} | Liar: {l_mean*20:>+6.1f}")
        for n, s in b_scores:
            print(f"      {n:<28s} {s*20:>+6.1f}")

    print("=" * 115)


if __name__ == "__main__":
    main()
