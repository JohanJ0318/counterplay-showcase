"""Shared schema: the feature contract between parsing, training, and ranking.

Everything downstream imports FEATURES from here. If you add a feature, add it
in one place and the whole pipeline picks it up.
"""

# Model features. Deliberately count-based: no player positions.
# Win probability moves when someone dies, and a lost duel *is* the death.
FEATURES = [
    "tier_id",
    # WHERE the bomb went, not just that it went. 0 until the plant fires,
    # then 1 or 2 as CS2 numbers the sites. It is 0 before the plant on
    # purpose: the round knows its site all along, the model must not.
    "plant_site",
    "alive_ct",
    "alive_t",
    "equip_ct",
    "equip_t",
    "time_left",
    "bomb_planted",
    "time_since_plant",
    "map_id",
    "round_type_id",
]

CATEGORICAL = ["map_id", "round_type_id", "tier_id", "plant_site"]

# Where everyone stands, summarised for a tree model (counterplay/posfeat.py
# computes them from round_positions and the death events). Read by the
# "smallpos" model config, not part of FEATURES: the shipped config, and
# anything still trained on FEATURES alone, never saw them.
POSFEAT = ["hp_ct", "hp_t", "ct_site1", "ct_site2", "t_site1", "t_site2",
           "ct_spread", "t_spread", "closest_enemy"]

# Label: did the CT side win this round. T-side WP is 1 - p.
LABEL = "ct_won"

ROUND_SECONDS = 115.0      # competitive round timer
PLANT_SECONDS = 40.0       # post-plant timer

# APPEND to this list, never insert. MAP_IDS is positional, so inserting
# renumbers every map after it and silently relabels existing rounds.
#
# de_cache was missing until 2026-09-24, and MAP_IDS.get(name, 0) returns 0,
# which is de_mirage. 133 collegiate rounds across 6 maps trained as Mirage
# next to 819 real Mirage rounds. A default that happens to be a valid id is
# worse than no default, because nothing can tell the two apart afterwards.
MAPS = ["de_mirage", "de_inferno", "de_nuke", "de_ancient",
        "de_dust2", "de_anubis", "de_train", "de_overpass", "de_cache"]
MAP_IDS = {m: i for i, m in enumerate(MAPS)}

# Anything not on the list above. Do NOT default a lookup to 0: that is
# de_mirage, and a map defaulting to a real map is indistinguishable from the
# real thing afterwards. This is what cost 133 de_cache rounds.
UNKNOWN_MAP_ID = len(MAPS)

ROUND_TYPES = ["pistol", "eco", "force", "full"]
ROUND_TYPE_IDS = {r: i for i, r in enumerate(ROUND_TYPES)}

# Skill tiers. These are not arbitrary buckets — they are the customer
# segments, which is why they are worth conditioning on. The same 4v2 retake
# is a very different proposition in tier-1 CS than in solo-queue Premier, and
# a model that averages them is wrong for everybody. Conditioning on tier means
# one model serves all four populations honestly instead of serving none.
#
# APPEND only, like MAPS: TIER_IDS is positional. "esea" (2026-10-14) is the
# ESEA League on FACEIT (tools/esea.py), kept apart from "league" so an ESEA
# match never counts as a college one. Without its own entry state.py would
# file it under DEFAULT_TIER, silently.
TIERS = ["pro", "collegiate", "league", "premier", "esea"]
TIER_IDS = {t: i for i, t in enumerate(TIERS)}
DEFAULT_TIER = "premier"


def classify_round(equip_value: float, round_num: int) -> str:
    """Bucket a side's round by its start-of-round equipment value."""
    if round_num in (1, 13):
        return "pistol"
    if equip_value < 5000:
        return "eco"
    if equip_value < 20000:
        return "force"
    return "full"
