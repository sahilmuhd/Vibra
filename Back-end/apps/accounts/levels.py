"""Levels and VIP, all derived from coin totals kept on the Profile.

wealth_xp = coins this user has spent on gifts   -> wealth level + VIP tier
charm_xp  = coins this user has received in gifts -> charm level

Level L is reached at 100 * (L-1)^2 xp: 0 -> Lv1, 100 -> Lv2, 400 -> Lv3,
10 000 -> Lv11 ... capped at Lv99.
"""
import math

MAX_LEVEL = 99

# (tier, coins spent needed)
VIP_TIERS = [(1, 1_000), (2, 10_000), (3, 50_000), (4, 200_000), (5, 1_000_000)]


def level_for(xp: int) -> int:
    return min(MAX_LEVEL, math.isqrt(max(0, int(xp)) // 100) + 1)


def xp_for_level(level: int) -> int:
    return 100 * (max(1, level) - 1) ** 2


def level_progress(xp: int) -> dict:
    """Current level, and how far along the way to the next one."""
    lvl = level_for(xp)
    start, end = xp_for_level(lvl), xp_for_level(min(MAX_LEVEL, lvl + 1))
    return {
        "level": lvl, "xp": int(xp),
        "level_start": start, "next_level_at": end if lvl < MAX_LEVEL else None,
    }


def vip_for(wealth_xp: int) -> int:
    tier = 0
    for t, need in VIP_TIERS:
        if wealth_xp >= need:
            tier = t
    return tier


def vip_progress(wealth_xp: int) -> dict:
    tier = vip_for(wealth_xp)
    nxt = next((need for t, need in VIP_TIERS if t == tier + 1), None)
    return {"tier": tier, "spent": int(wealth_xp), "next_tier_at": nxt,
            "tiers": [{"tier": t, "needs": need} for t, need in VIP_TIERS]}
