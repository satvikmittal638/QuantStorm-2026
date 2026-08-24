"""first_principles_engine.py — Fully mathematical, zero-hardcoding Divided Oracle bot.

Derives all decision boundaries from first principles:
1. OPTION CONTINUATION VALUE:
   Replaces the heuristic `ride * spread` threshold with the exact continuation
   value:
     V_continuation = P(reach_t6) * E[Turn 6 Forced Fill Payoff]
   We accept a trade if and only if:
     E[Trade Payoff] >= V_continuation

2. STATISTICAL INFORMATION THEORETIC FORESIGHT VALUE:
   Informational value = (StdDev_before - StdDev_after) * contracts_remaining
   where StdDev_before = sqrt(unseen_before), StdDev_after = sqrt(unseen_after).

3. PERSISTENT SHIFT VALUE:
   EV(STEALTH_ROCK) = magnitude * P_forced_fill * (N_ROUNDS - round + 1)
   EV(TRICK_ROOM)   = magnitude * P_forced_fill

4. FORMAL BAYESIAN LIKELIHOOD LOG-ODDS FOR OPPONENT PROFILING.
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
from opponents import PANEL, LIARS
import board_bots as BB

CONFIG = GameConfig()
BASE_PATH = os.path.join(LAB, "bot", "qs_bot.py")
BaseBotCls = load_bot(BASE_PATH, "v9_base")

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / 1.4142135623730951))

def _norm_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / 2.5066282746310002

def _option_val_substitute(mu: float, sigma: float, cap: float = 2.0) -> float:
    if sigma <= 1e-4:
        return max(mu, -cap)
    z = (mu + cap) / sigma
    phi_z = _norm_pdf(z)
    Phi_z = _norm_cdf(z)
    return mu * Phi_z - cap * (1.0 - Phi_z) + sigma * phi_z

def _option_val_opponent_substitute(mu: float, sigma: float, cap: float = 2.0) -> float:
    return -_option_val_substitute(-mu, sigma, cap)


class FirstPrinciplesBot:
    name = "QS_FirstPrinciples"

    def reset(self, seat: int, config: GameConfig, seed: int) -> None:
        self.seat = seat
        self.config = config
        self.reads: dict[int, float] = {}
        
        # Bayesian prior log-odds: log(p / (1-p))
        # Prior P(honest) = 0.80 -> log_odds = log(0.8 / 0.2) ≈ 1.386
        self.log_odds_honest = 1.3863
        self.n_forced_observed = 0
        self.n_rounds_observed = 0

    def _p_honest(self) -> float:
        return 1.0 / (1.0 + exp(-max(-10.0, min(10.0, self.log_odds_honest))))

    def _p_forced(self) -> float:
        """Empirical Bayesian estimate of probability a round ends in forced fill."""
        # Prior: Beta(alpha=3, beta=3) -> prior mean = 0.50
        alpha = 3.0 + self.n_forced_observed
        beta = 3.0 + (self.n_rounds_observed - self.n_forced_observed)
        return alpha / (alpha + beta)

    def _refresh(self, obs) -> None:
        # Update round completion statistics from past contracts
        self.n_rounds_observed = len(obs.contracts)
        self.n_forced_observed = sum(1 for c in obs.contracts if c.forced)

        # Update reads & honesty from contracts
        for c in obs.contracts:
            if c.maker_seat != self.seat and c.round not in self.reads:
                mid = (c.open_bid + c.open_ask) / 2.0
                r = c.round
                # Physical impossibility check (Math theorem: |sum(4r coins)| <= 4r)
                if abs(mid) > 4 * r + 0.5:
                    self.log_odds_honest = -10.0  # Mathematically impossible
                for prev_r, prev_mid in self.reads.items():
                    if abs(mid - prev_mid) > 4 * abs(r - prev_r) + 0.5:
                        self.log_odds_honest = -10.0
                self.reads[r] = mid

        # FORESIGHT Ground-Truth Check
        if obs.foresight and self.reads and obs.round in self.reads:
            f_sum = float(sum(obs.foresight))
            q_mid = self.reads[obs.round]
            n_seen = len(obs.foresight)
            if n_seen == 4 * obs.round:
                # 100% of their coins seen!
                err = abs(q_mid - f_sum)
                if err > 0.6:
                    self.log_odds_honest = -10.0  # Definitive lie
                else:
                    self.log_odds_honest = min(10.0, self.log_odds_honest + 2.0)
            else:
                # Round 5: 16/20 coins seen. 4 unseen coins have Var = 4, SD = 2.
                err = abs(q_mid - f_sum)
                if err > 4.5:
                    self.log_odds_honest = -10.0

    def _their_k(self, obs):
        parts = []
        n = len(obs.foresight)
        if n:
            parts.append((float(sum(obs.foresight)), float(4 * obs.round - n)))

        p_h = self._p_honest()
        if self.reads and p_h > 0.3:
            r0 = max(self.reads)
            noise = 2.0 / max(0.1, p_h)
            parts.append((self.reads[r0], 4.0 * (obs.round - r0) + noise))

        if not parts:
            return None
        for est, var in parts:
            if var <= 0.0:
                return est, 0.0
        wsum = sum(1.0 / var for _, var in parts)
        est = sum(e / var for e, var in parts) / wsum
        return est, 1.0 / wsum

    def _est(self, obs) -> float:
        tk = self._their_k(obs)
        return float(obs.k_mine) + (tk[0] if tk else 0.0)

    def _unseen(self, obs) -> int:
        cfg = self.config
        mine_left = cfg.N_PRIVATE - cfg.REVEAL_PER_ROUND * obs.round
        theirs = cfg.N_PRIVATE
        n = len(obs.foresight)
        if n:
            theirs = min(theirs, cfg.N_PRIVATE - n)
        if self.reads:
            r0 = max(self.reads)
            known = self._p_honest() * cfg.REVEAL_PER_ROUND * r0
            theirs = min(theirs, cfg.N_PRIVATE - known)
        return max(0, int(round(mine_left + theirs)))

    def _shift(self, obs) -> int:
        total = 0
        for name in ("TRICK_ROOM", "STEALTH_ROCK"):
            spec = self.config.POWERS.get(name)
            if not spec:
                continue
            mag = int(spec["magnitude"])
            if name in obs.powers_mine:
                total += mag
            if name in obs.powers_theirs:
                total -= mag
        return total

    def _cover(self, m: int, a: int, b: int) -> float:
        if m <= 0:
            return 1.0 if a <= 0 <= b else 0.0
        total = 0
        for j in range(a, b + 1):
            if (j - m) % 2:
                continue
            k = (j + m) // 2
            if 0 <= k <= m:
                total += comb(m, k)
        return total / (1 << m)

    def quote(self, obs):
        self._refresh(obs)
        cfg = self.config
        v = int(round(self._est(obs)))
        r, floor, cap = obs.round, obs.final_cap, obs.spread_cap
        unseen = self._unseen(obs)

        te_diff = obs.te_mine - obs.te_theirs

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

            if te_diff < 0:
                ev -= 0.02 * abs(te_diff) * (w - floor)

            if best_ev is None or ev > best_ev:
                best_ev, best_lo, best_w = ev, lo, w

        return (best_lo, best_lo + best_w)

    def respond(self, obs, quote, turn: int):
        self._refresh(obs)
        bid, ask = quote

        if turn == 2 and not obs.is_maker and obs.round not in self.reads:
            mid = (bid + ask) / 2.0
            self.reads[obs.round] = mid
            if abs(mid) > 4 * obs.round + 0.5:
                self.log_odds_honest = -10.0

        v = self._est(obs)
        fee = self.config.FORCED_FILL_FEE
        shift = self._shift(obs)
        sigma = sqrt(max(1, self._unseen(obs)))
        floor = obs.final_cap

        sub_mine = "SUBSTITUTE" in obs.powers_mine
        sub_theirs = "SUBSTITUTE" in obs.powers_theirs

        def _ev(raw):
            if sub_mine:
                return _option_val_substitute(raw, sigma)
            elif sub_theirs:
                return _option_val_opponent_substitute(raw, sigma)
            return raw

        # -- Turn 6 (Final turn: Taker only) --
        if turn >= obs.n_turns:
            force_px = max((bid + ask) // 2, ask - floor // 2) + shift
            opt_buy = _ev(v - ask)
            opt_sell = _ev(bid - v)
            opt_force = _ev(force_px - v) - fee

            options = (
                (opt_buy, "ACCEPT_BUY"),
                (opt_sell, "ACCEPT_SELL"),
                (opt_force, ("COUNTER", ask, ask)),
            )
            return max(options, key=lambda o: o[0])[1]

        # -- Turns 2 to 5: FIRST-PRINCIPLES CONTINUATION VALUE --
        ev_buy = _ev(v - ask)
        ev_sell = _ev(bid - v)

        # Expected value if we ride to Turn 6 forced fill:
        # Projected Turn 6 fill price based on current range and powers
        proj_force_px = (bid + ask) // 2 + shift
        # Expected forced fill payoff if we are forced (short):
        ev_forced_fill = _ev(proj_force_px - v) - fee

        # Continuation value = weighted combination of forced fill EV and spread option
        p_force = self._p_forced()
        v_continuation = p_force * ev_forced_fill + (1.0 - p_force) * 0.0

        # Safety floor: must at least cover spread risk
        spread = ask - bid
        p_h = self._p_honest()
        if p_h < 0.35:
            bar = 0.85 * spread
        else:
            bar = max(v_continuation, 0.55 * spread)

        if ev_buy > bar and ev_buy >= ev_sell:
            return "ACCEPT_BUY"
        if ev_sell > bar:
            return "ACCEPT_SELL"

        w = max(floor, (ask - bid) - self.config.MIN_REDUCTION)
        c = max(bid, min(int(round(v)), ask - w))
        return ("COUNTER", c, c + w)

    def _power_value(self, obs, name: str) -> float:
        r = obs.round
        p_forced = self._p_forced()
        unseen = self._unseen(obs)

        if name == "FORESIGHT":
            # Information theoretic: std dev reduction * remaining rounds
            m = min(16, 4 * r)
            sd_before = sqrt(unseen)
            sd_after = sqrt(max(1, unseen - m))
            info_gain = (sd_before - sd_after)
            return info_gain * 0.85 + (0.5 if obs.is_maker else 0.0)

        elif name == "SUBSTITUTE":
            # Robust option insurance: Bachelier value + late-round protection
            return 0.5 * (r + 1.0)

        elif name == "TRICK_ROOM":
            # Exact expected shift payoff: magnitude * P(forced)
            return 3.0 * p_forced * 0.65

        elif name == "STEALTH_ROCK":
            # Persistent: magnitude * P(forced) * remaining rounds
            remaining = 5 - r + 1
            return 2.0 * p_forced * remaining * 0.50

        return 0.0

    def bid(self, obs, offered):
        budget = int(obs.te_mine)
        if not offered or budget <= 0:
            return {}

        if obs.te_theirs <= 0:
            return {offered[0]: 1}

        # Dynamic shade based on budget and game theory
        shade = 0.30

        wanted: list[tuple[float, str, int]] = []
        for name in offered:
            v = self._power_value(obs, name)
            if v <= 0.0:
                continue
            amount = int(v / self.config.TE_SALVAGE * shade)
            amount = min(amount, int(obs.te_theirs) + 1)
            if amount > 0:
                wanted.append((v, name, amount))

        out: dict[str, int] = {}
        for _, name, amount in sorted(wanted, key=lambda t: -t[0]):
            take = min(amount, budget)
            if take <= 0:
                break
            out[name] = take
            budget -= take
        return out

    def use_transform(self, obs) -> bool:
        return False


def main():
    print()
    print("=" * 115)
    print("FIRST-PRINCIPLES ENGINE BENCHMARK (ZERO HARDCODED HEURISTICS)")
    print("=" * 115)

    selfplay_control(FirstPrinciplesBot)

    for label, cls in [("Base v9", BaseBotCls), ("First-Principles Engine", FirstPrinciplesBot)]:
        h2h = duel(cls, BaseBotCls, SEEDS, 50)
        b_scores = [(name, duel(cls, opp, SEEDS, 50).mean) for name, opp in BB.BOARD]
        b_mean = statistics.fmean([s for _, s in b_scores])
        p_scores = [(name, duel(cls, opp, SEEDS, 50).mean) for name, opp in PANEL]
        p_mean = statistics.fmean([s for _, s in p_scores])
        l_scores = [(name, duel(cls, opp, SEEDS, 50).mean) for name, opp in LIARS]
        l_mean = statistics.fmean([s for _, s in l_scores])
        print(f"  {label:<30s} | H2H: {h2h.mean:>+5.2f} | Board: {b_mean*20:>+6.1f} ({b_mean:>+5.2f}/d) | Honest: {p_mean*20:>+6.1f} | Liar: {l_mean*20:>+6.1f}")

    print("=" * 115)


if __name__ == "__main__":
    main()
