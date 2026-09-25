"""What a player can buy, by kind.

The buy analysis reads loadouts as KINDS (rifle, SMG, pistol) rather than as
prices. Prices are read from the demo itself (`current_equip_value`,
`cash_spent_this_round`), which follows every patch without anyone editing
this file. A kind does not change when Valve moves a price.

Anything not listed here is not something a player buys: knives (every skin
has its own name), the C4, a zeus picked up off the floor. A weapon added in
a future update is also missing until it is listed, and drops out of the
loadout rather than being guessed at.
"""
from __future__ import annotations

PISTOL, SMG, HEAVY, RIFLE, SNIPER, GRENADE = (
    "pistol", "smg", "heavy", "rifle", "sniper", "grenade")

KIND = {
    # pistols
    "Glock-18": PISTOL, "USP-S": PISTOL, "P2000": PISTOL, "P250": PISTOL,
    "Five-SeveN": PISTOL, "Tec-9": PISTOL, "CZ75-Auto": PISTOL,
    "Dual Berettas": PISTOL, "Desert Eagle": PISTOL, "R8 Revolver": PISTOL,
    # SMGs
    "MAC-10": SMG, "MP9": SMG, "MP7": SMG, "MP5-SD": SMG, "UMP-45": SMG,
    "P90": SMG, "PP-Bizon": SMG,
    # shotguns and machine guns
    "Nova": HEAVY, "XM1014": HEAVY, "Sawed-Off": HEAVY, "MAG-7": HEAVY,
    "M249": HEAVY, "Negev": HEAVY,
    # rifles
    "Galil AR": RIFLE, "FAMAS": RIFLE, "AK-47": RIFLE, "M4A4": RIFLE,
    "M4A1-S": RIFLE, "SG 553": RIFLE, "AUG": RIFLE,
    # snipers
    "SSG 08": SNIPER, "AWP": SNIPER, "G3SG1": SNIPER, "SCAR-20": SNIPER,
    # utility
    "Flashbang": GRENADE, "Smoke Grenade": GRENADE,
    "High Explosive Grenade": GRENADE, "Molotov": GRENADE,
    "Incendiary Grenade": GRENADE, "Decoy Grenade": GRENADE,
}

# Strongest first: a player holding an AWP and a Deagle is an AWP buy.
_RANK = [SNIPER, RIFLE, HEAVY, SMG, PISTOL]


def loadout(inventory) -> str | None:
    """A freeze-end inventory as the buyable items in it, comma separated.

    None when the demo gave no inventory at all, so "unknown" never reads
    as "bought nothing"."""
    if inventory is None or not hasattr(inventory, "__iter__") \
            or isinstance(inventory, str):
        return None
    items = [str(i) for i in inventory if str(i) in KIND]
    return ", ".join(items)


def main_weapon(loadout_text: str | None) -> str | None:
    """The kind of the best gun in a loadout: sniper, rifle, heavy, smg or
    pistol. None when there is no loadout to read."""
    if loadout_text is None:
        return None
    kinds = {KIND[i] for i in loadout_text.split(", ") if i in KIND}
    return next((k for k in _RANK if k in kinds), PISTOL)
