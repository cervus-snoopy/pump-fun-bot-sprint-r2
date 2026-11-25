"""Late-Curve Completion Rider v2 for pump.fun replay.

Lessons from v3 (dev grade -0.729 SOL, 18 trips, win 0%):
- Removing the trail entirely was worse than v2 (-0.270). The winners spike
  and then crash to near zero in minutes; without a trail the bot rode them
  all the way down (worst coin -0.125 SOL on a 0.10 stake). v4 restores a
  WIDER trail (arm +30%, drop -20%) so winners are banked but not cut on
  noise. Stats: capping winners at +25% collapses EV, but holding to the end
  collapses harder on this window because the end price of a spiked coin is
  usually a crash, not a completion.
- v3's sell orders used 1000bps slippage and were REJECTED while coins
  free-fell, so stops never executed at the stop price. v4 uses 5000bps for
  sells so exits actually fill.
- v2/v3 counted every trader as a "buyer"; the stats filter counts only
  is_buy users. v4 counts buyers only, matching the filter the stats were
  built on (fewer than 60 unique buyers, creator net under 0.2 SOL).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bot

LAMPORTS_PER_SOL = makefun_bot.LAMPORTS_PER_SOL
SCALE = 10 ** 12

TIER1_RQ = 30 * LAMPORTS_PER_SOL
TIER1_STAKE = LAMPORTS_PER_SOL // 10          # 0.10 SOL
TIER2_RQ = 20 * LAMPORTS_PER_SOL
TIER2_STAKE = LAMPORTS_PER_SOL // 20          # 0.05 SOL
MAX_UNIQ_BUYERS = 60
MAX_CREATOR_NET = LAMPORTS_PER_SOL // 5       # 0.2 SOL
STOP_BPS = 1000                                # -10% hard stop, from fill price
TRAIL_ARM_BPS = 3000                           # trail starts once +30%
TRAIL_DROP_BPS = 2000                          # exit on -20% from peak
STALE_SLOTS = 8000
SLIPPAGE_BPS = 1000
SELL_SLIPPAGE_BPS = 5000                       # sells must execute in a crash
MAX_POSITIONS = 5
T2_MAX_COMMITTED = 4


def price_of(curve):
    if curve.virtual_token_reserves <= 0:
        return 0
    return curve.virtual_quote_reserves * SCALE // curve.virtual_token_reserves


class Mint:
    __slots__ = ("creator", "created_slot", "buyers", "creator_net",
                 "peak_mult", "peak_slot", "bottom", "bottom_slot",
                 "first_price", "seen_rq30", "seen_rq20", "seen_rq30_slot",
                 "seen_rq20_slot", "tried1", "tried2", "tried3")

    def __init__(self, creator, slot):
        self.creator = creator
        self.created_slot = slot
        self.buyers = {}
        self.creator_net = 0
        self.peak_mult = 10000
        self.peak_slot = slot
        self.bottom = 0
        self.bottom_slot = -1
        self.first_price = 0
        self.seen_rq30 = False
        self.seen_rq20 = False
        self.seen_rq30_slot = -1
        self.seen_rq20_slot = -1
        self.tried1 = False
        self.tried2 = False
        self.tried3 = False


class Bot:
    def __init__(self):
        self.mints = {}
        self.positions = {}       # mint -> dict(entry, peak, slot, tier)
        self.pending_buys = {}    # client_id -> (mint, tier)
        self.next_id = 1

    def mint(self, mid, creator, slot):
        m = self.mints.get(mid)
        if m is None:
            m = Mint(creator, slot)
            self.mints[mid] = m
        return m

    def on_batch(self, state, batch):
        # Learn fill prices first: a buy fill anchors the position's entry.
        for f in batch["fills"]:
            if f["status"] != "filled":
                self.pending_buys.pop(f["client_id"], None)
                continue
            if f["side"] == "buy":
                info = self.pending_buys.pop(f["client_id"], None)
                if info is not None:
                    mid, tier = info
                    tokens = int(f["token_amount"])
                    quote = int(f["quote_lamports"])
                    if tokens > 0 and quote > 0:
                        entry = quote * SCALE // tokens
                        self.positions[mid] = {"entry": entry, "peak": entry,
                                               "slot": state.slot, "tier": tier}
            else:
                # A sell fill (ours or a harness close) ends the position.
                self.positions.pop(f["mint"], None)

        # Fold this batch's events into per-mint features.
        for e in batch["events"]:
            kind = e["event"]
            mid = e["mint"]
            if kind == "CreateEvent":
                m = self.mint(mid, e.get("creator", ""), e["slot"])
                m.creator = e.get("creator", "")
            elif kind == "TradeEvent":
                m = self.mint(mid, e.get("creator", ""), e["slot"])
                user = e["user"]
                if e["is_buy"]:
                    m.buyers[user] = 1
                amt = int(e["sol_amount"])
                if user == m.creator:
                    m.creator_net += amt if e["is_buy"] else -amt
                curve = state.curves.get(mid)
                if curve is not None:
                    p = price_of(curve)
                    if m.first_price == 0:
                        m.first_price = p
                    if p > 0 and m.first_price > 0:
                        mult = p * 10000 // m.first_price
                        if mult > m.peak_mult:
                            m.peak_mult = mult
                            m.peak_slot = e["slot"]
                            m.bottom = 0
                            m.bottom_slot = -1
                    if m.peak_mult >= 20000 and p > 0:
                        peak_price = m.first_price * m.peak_mult // 10000
                        if p <= peak_price * 75 // 100:
                            if m.bottom == 0 or p < m.bottom:
                                m.bottom = p
                                m.bottom_slot = e["slot"]

        orders = []
        committed = state.committed_position_count()
        for mid, curve in state.curves.items():
            if curve.complete:
                continue
            m = self.mints.get(mid)
            if m is None:
                continue
            if mid in self.positions:
                continue
            rq = curve.real_quote_reserves
            p = price_of(curve)
            if p <= 0:
                continue
            # Tier 1: late curve at 30 SOL real, filtered. Retry 200 slots.
            if rq >= TIER1_RQ and not m.tried1:
                if not m.seen_rq30:
                    m.seen_rq30 = True
                    m.seen_rq30_slot = state.slot
                if state.slot - m.seen_rq30_slot <= 200:
                    if len(m.buyers) < MAX_UNIQ_BUYERS and m.creator_net < MAX_CREATOR_NET:
                        if committed < MAX_POSITIONS and self.try_buy(
                                state, orders, mid, TIER1_STAKE, 1):
                            m.tried1 = True
                            committed += 1
                            continue
            # Tier 2: breadth at 20 SOL real, same filter, slots reserved.
            if rq >= TIER2_RQ and not m.tried2:
                if not m.seen_rq20:
                    m.seen_rq20 = True
                    m.seen_rq20_slot = state.slot
                if state.slot - m.seen_rq20_slot <= 200:
                    if len(m.buyers) < MAX_UNIQ_BUYERS and m.creator_net < MAX_CREATOR_NET:
                        if committed < T2_MAX_COMMITTED and self.try_buy(
                                state, orders, mid, TIER2_STAKE, 2):
                            m.tried2 = True
                            committed += 1

        orders.extend(self.exits(state))
        return orders

    def try_buy(self, state, orders, mid, stake, tier):
        cap = state.max_buy_lamports(mid)
        if cap <= 0:
            return False
        amt = stake if stake <= cap else cap
        if amt < LAMPORTS_PER_SOL // 100:
            return False
        if state.free_cash_lamports() < amt + state.tx_fee_lamports():
            return False
        cid = "b%d" % self.next_id
        self.next_id += 1
        orders.append({"side": "buy", "client_id": cid, "mint": mid,
                       "quote_lamports": amt, "max_slippage_bps": SLIPPAGE_BPS})
        self.pending_buys[cid] = (mid, tier)
        return True

    def exits(self, state):
        orders = []
        for mid, pos in list(self.positions.items()):
            holding = state.positions.get(mid)
            if holding is None:
                if not any(p.order["mint"] == mid and p.order["side"] == "buy"
                           for p in state.pending.values()):
                    self.positions.pop(mid, None)
                continue
            curve = state.curves.get(mid)
            if curve is None or curve.complete:
                self.positions.pop(mid, None)
                continue
            p = price_of(curve)
            if p <= 0:
                continue
            if p > pos["peak"]:
                pos["peak"] = p
            entry = pos["entry"]
            sell = False
            if p * 10000 // entry <= 10000 - STOP_BPS:
                sell = True
            elif pos["peak"] * 10000 // entry >= 10000 + TRAIL_ARM_BPS:
                if p * 10000 // pos["peak"] <= 10000 - TRAIL_DROP_BPS:
                    sell = True
            elif state.slot - pos["slot"] > STALE_SLOTS and p < entry * 105 // 100:
                sell = True
            if sell:
                orders.append({"side": "sell", "mint": mid,
                               "token_amount": holding.token_amount,
                               "max_slippage_bps": SELL_SLIPPAGE_BPS})
                self.positions.pop(mid, None)
        return orders


def main():
    bot = Bot()
    makefun_bot.run(bot.on_batch)


if __name__ == "__main__":
    main()
