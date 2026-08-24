"""internal_tournament.py — Round-Robin Tournament among Variations of the Current Bot.

Variations Competing:
1. QS_Base: Current baseline (shade=0.33, sr=0.25, ride=0.65, fs=0.75)
2. QS_AuctionAggro: Aggressive power bidder (shade=0.40, sr=0.30, fs=0.85)
3. QS_SalvageHoarder: Conservative budget preserver (shade=0.22, sr=0.18, fs=0.60)
4. QS_EarlySettler: Low ride hurdle (ride=0.50, settles trades early)
5. QS_EndgameForcer: High ride hurdle (ride=0.80, forces Turn 6)
6. QS_TightMaker: Tighter quotes for reduced straddle variance
7. QS_WideMaker: Wider quotes to harvest maximum maker obligation
8. QS_StrictForensics: Hyper-strict honesty filter
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
from arena import load_bot, duel, SEEDS, N_DEALS, selfplay_control

CONFIG = GameConfig()
BOT_PATH = os.path.join(LAB, "bot", "qs_bot.py")
BaseBotCls = load_bot(BOT_PATH, "tournament_base")

def _norm_cdf(x): return 0.5 * (1.0 + erf(x / 1.4142135623730951))
def _norm_pdf(x): return exp(-0.5 * x * x) / 2.5066282746310002
def _opt_sub(mu, sigma, cap=2.0):
    if sigma <= 1e-4: return max(mu, -cap)
    z = (mu + cap) / sigma
    return mu * _norm_cdf(z) - cap * (1.0 - _norm_cdf(z)) + sigma * _norm_pdf(z)
def _opt_opp_sub(mu, sigma, cap=2.0):
    return -_opt_sub(-mu, sigma, cap)


def create_variant(name, shade=0.33, sr_rate=0.25, fs_scale=0.75, base_ride=0.65, inv_pen=0.02, strict_err=2.5, width_bias=0.0):
    class V(BaseBotCls):
        pass
    V.name = f"QS_{name}"

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

    def _refresh(self, obs):
        if obs.auction_log:
            opp_wins = [e for e in obs.auction_log if e["seat"] != self.seat]
            if opp_wins:
                last_win = opp_wins[-1]
                if last_win["cost"] >= 5:
                    self.p_passive *= 0.2
                    self.p_forcer = min(1.0, self.p_forcer + 0.3)
                elif last_win["cost"] == 0:
                    self.p_passive = min(1.0, self.p_passive + 0.3)

        for c in obs.contracts:
            if c.maker_seat != self.seat and c.round not in self.reads:
                mid = (c.open_bid + c.open_ask) / 2.0
                r = c.round
                if abs(mid) > 4 * r + 1.0:
                    self.p_honest *= 0.1
                for prev_r, prev_mid in self.reads.items():
                    if abs(mid - prev_mid) > 4 * abs(r - prev_r) + 1.0:
                        self.p_honest *= 0.1
                self.reads[r] = mid

        if obs.foresight and self.reads and obs.round in self.reads:
            f_sum = float(sum(obs.foresight))
            q_mid = self.reads[obs.round]
            if abs(q_mid - f_sum) > strict_err:
                self.p_honest = 0.0
            else:
                self.p_honest = min(1.0, self.p_honest + 0.2)

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
            ev = (cfg.MAKER_OBLIGATION * (true_p - priced) - (cfg.WIDTH_PREMIUM + width_bias) * (w - floor))
            if te_inventory_cushion < 0:
                ev -= inv_pen * abs(te_inventory_cushion) * (w - floor)
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
            ride = max(0.40, base_ride - 0.15)
        elif info_count > 2:
            ride = max(0.45, base_ride - 0.10)
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

    V._power_value = _power_val
    V._refresh = _refresh
    V.quote = _quote
    V.respond = _respond
    V.bid = _bid
    return V


VARIANTS = [
    ("QS_Base", BaseBotCls),
    ("QS_AuctionAggro", create_variant("AuctionAggro", shade=0.40, sr_rate=0.30, fs_scale=0.85)),
    ("QS_SalvageHoarder", create_variant("SalvageHoarder", shade=0.22, sr_rate=0.18, fs_scale=0.60)),
    ("QS_EarlySettler", create_variant("EarlySettler", base_ride=0.50)),
    ("QS_EndgameForcer", create_variant("EndgameForcer", base_ride=0.80)),
    ("QS_TightMaker", create_variant("TightMaker", width_bias=0.08)),
    ("QS_WideMaker", create_variant("WideMaker", width_bias=-0.04)),
    ("QS_StrictForensics", create_variant("StrictForensics", strict_err=0.6)),
]


def run_tournament(n_deals_per_pair=40):
    n_bots = len(VARIANTS)
    matrix = [[0.0] * n_bots for _ in range(n_bots)]
    total_scores = [0.0] * n_bots
    records = [{"W": 0, "D": 0, "L": 0} for _ in range(n_bots)]

    print()
    print("=" * 115)
    print("ROUND-ROBIN TOURNAMENT: 8 BOT VARIATIONS HEAD-TO-HEAD")
    print(f"Config: {len(SEEDS)} seeds x {n_deals_per_pair * 2} mirrored deals per matchup")
    print("=" * 115)

    for i in range(n_bots):
        for j in range(i, n_bots):
            name_i, bot_i = VARIANTS[i]
            name_j, bot_j = VARIANTS[j]
            if i == j:
                matrix[i][j] = 0.0
            else:
                res = duel(bot_i, bot_j, SEEDS, n_deals_per_pair)
                matrix[i][j] = res.mean
                matrix[j][i] = -res.mean
                total_scores[i] += res.mean * 20
                total_scores[j] -= res.mean * 20

                if res.mean > 0.05:
                    records[i]["W"] += 1; records[j]["L"] += 1
                elif res.mean < -0.05:
                    records[i]["L"] += 1; records[j]["W"] += 1
                else:
                    records[i]["D"] += 1; records[j]["D"] += 1

    # Print Crosstable Matrix
    header = f"{'Variant':<20s} " + "".join(f"{f'[{k}]':>8s}" for k in range(n_bots)) + " | Net /match"
    print("\nCROSS-TABLE MATRIX (Row vs Column, in ticks/deal):")
    print("-" * len(header))
    print(header)
    print("-" * len(header))
    for i in range(n_bots):
        row_str = f"[{i}] {VARIANTS[i][0]:<16s} "
        for j in range(n_bots):
            if i == j:
                row_str += f"{'--':>8s}"
            else:
                row_str += f"{matrix[i][j]:>+8.2f}"
        row_str += f" | {total_scores[i]:>+9.1f}"
        print(row_str)
    print("-" * len(header))

    # Print Final Leaderboard Rankings
    ranked_indices = sorted(range(n_bots), key=lambda idx: -total_scores[idx])
    print("\n" + "=" * 80)
    print("FINAL TOURNAMENT STANDINGS")
    print("=" * 80)
    print(f"{'Rank':<6s} {'Bot Variation':<24s} {'Net PnL / match':<18s} {'Avg ticks/deal':<18s} {'Record (W-D-L)':<15s}")
    print("-" * 80)
    for rank, idx in enumerate(ranked_indices, 1):
        name = VARIANTS[idx][0]
        net = total_scores[idx]
        avg_tick = net / (20 * (n_bots - 1))
        rec = f"{records[idx]['W']}W - {records[idx]['D']}D - {records[idx]['L']}L"
        print(f"#{rank:<5d} {name:<24s} {net:>+15.1f}     {avg_tick:>+15.2f}     {rec:<15s}")
    print("=" * 80)


if __name__ == "__main__":
    run_tournament()
