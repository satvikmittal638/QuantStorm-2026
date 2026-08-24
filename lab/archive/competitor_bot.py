"""competitor_bot.py — High-fidelity reconstruction of the +168.69 Leaderboard Competitor.

Core Pillars:
1. Early-Trade Arbitrage on Compressed Quotes (Low Hurdle on Turn 2).
2. High-Salvage / Patient Auction Engine (concedes TRANSFORM/TRICK_ROOM, hoards TE, snipes 1 TE when opponent is broke).
3. Autonomous Estimator (prices purely on k_mine + foresight, immune to quote poisoning).
"""

from __future__ import annotations
import math
import random
from math import comb, erf, exp, sqrt

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / 1.4142135623730951))

def _norm_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / 2.5066282746310002

def _opt_sub(mu: float, sigma: float, cap: float = 2.0) -> float:
    if sigma <= 1e-4:
        return max(mu, -cap)
    z = (mu + cap) / sigma
    return mu * _norm_cdf(z) - cap * (1.0 - _norm_cdf(z)) + sigma * _norm_pdf(z)

def _opt_opp_sub(mu: float, sigma: float, cap: float = 2.0) -> float:
    return -_opt_sub(-mu, sigma, cap)


class CompetitorBot:
    name = "Competitor_Recon"

    def reset(self, seat: int, config, seed: int) -> None:
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)

    def _est(self, obs) -> float:
        """Autonomous estimation: relies solely on private coins + won foresight."""
        f_sum = float(sum(obs.foresight)) if obs.foresight else 0.0
        return float(obs.k_mine) + f_sum

    def _unseen(self, obs) -> int:
        cfg = self.config
        mine_left = cfg.N_PRIVATE - cfg.REVEAL_PER_ROUND * obs.round
        theirs = cfg.N_PRIVATE - (len(obs.foresight) if obs.foresight else 0)
        return max(0, int(round(mine_left + theirs)))

    def _shift(self, obs) -> int:
        total = 0
        for name in ("TRICK_ROOM", "STEALTH_ROCK"):
            spec = self.config.POWERS.get(name)
            if not spec: continue
            mag = int(spec["magnitude"])
            if name in obs.powers_mine: total += mag
            if name in obs.powers_theirs: total -= mag
        return total

    def _cover(self, m: int, a: int, b: int) -> float:
        if m <= 0: return 1.0 if a <= 0 <= b else 0.0
        total = 0
        for j in range(a, b + 1):
            if (j - m) % 2: continue
            k = (j + m) // 2
            if 0 <= k <= m: total += comb(m, k)
        return total / (1 << m)

    def quote(self, obs):
        cfg = self.config
        v = int(round(self._est(obs)))
        r, floor, cap = obs.round, obs.final_cap, obs.spread_cap
        unseen = self._unseen(obs)

        best_ev, best_lo, best_w = None, v - floor // 2, floor
        for w in range(floor, cap + 1):
            lo = v - w // 2
            if lo % 2: lo += 1
            try: priced = cfg.straddle_prob(r, w)
            except Exception: continue
            true_p = self._cover(unseen, lo - v, lo - v + w)
            ev = cfg.MAKER_OBLIGATION * (true_p - priced) - cfg.WIDTH_PREMIUM * (w - floor)
            if best_ev is None or ev > best_ev:
                best_ev, best_lo, best_w = ev, lo, w
        return (best_lo, best_lo + best_w)

    def respond(self, obs, quote, turn: int):
        bid, ask = quote
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
            return max([(opt_buy, "ACCEPT_BUY"), (opt_sell, "ACCEPT_SELL"),
                        (opt_force, ("COUNTER", ask, ask))], key=lambda o: o[0])[1]

        # Turns 2 to 5: EARLY-TRADE ARBITRAGE
        raw_buy = v - ask
        raw_sell = bid - v
        if "SUBSTITUTE" in obs.powers_mine:
            ev_buy = _opt_sub(raw_buy, sigma); ev_sell = _opt_sub(raw_sell, sigma)
        elif "SUBSTITUTE" in obs.powers_theirs:
            ev_buy = _opt_opp_sub(raw_buy, sigma); ev_sell = _opt_opp_sub(raw_sell, sigma)
        else:
            ev_buy = raw_buy; ev_sell = raw_sell

        # Low hurdle on Turn 2/3 (cannibalizes compressed/mispriced quotes)
        spread = ask - bid
        bar = 0.35 * spread  # Aggressive taker acceptance

        if ev_buy > bar and ev_buy >= ev_sell: return "ACCEPT_BUY"
        if ev_sell > bar: return "ACCEPT_SELL"

        w = max(floor, spread - self.config.MIN_REDUCTION)
        c = max(bid, min(int(round(v)), ask - w))
        return ("COUNTER", c, c + w)

    def bid(self, obs, offered):
        budget = int(obs.te_mine)
        if not offered or budget <= 0: return {}
        if obs.te_theirs <= 0: return {offered[0]: 1}

        # Concedes TRANSFORM (0) and TRICK_ROOM (low)
        r = obs.round
        wanted: list[tuple[float, str, int]] = []
        for n in offered:
            if n == "FORESIGHT":
                m = min(16, 4 * r)
                v = 0.70 * sqrt(m)
                amt = int(v / self.config.TE_SALVAGE * 0.24)
            elif n == "STEALTH_ROCK":
                v = 2.0 * 0.25 * (5 - r + 1)
                amt = int(v / self.config.TE_SALVAGE * 0.24)
            elif n == "SUBSTITUTE":
                v = 0.5 * (r + 1.0)
                amt = int(v / self.config.TE_SALVAGE * 0.20)
            else:
                continue

            amt = min(amt, int(obs.te_theirs) + 1)
            if amt > 0: wanted.append((v, n, amt))

        out: dict[str, int] = {}
        for _, n, amount in sorted(wanted, key=lambda t: -t[0]):
            take = min(amount, budget)
            if take <= 0: break
            out[n] = take
            budget -= take
        return out

    def use_transform(self, obs) -> bool:
        return False
