"""Shared schema: the feature contract between parsing, training, and ranking.

Everything downstream imports FEATURES from here. If you add a feature, add it
in one place and the whole pipeline picks it up.
"""

# Model features. Deliberately count-based: no player positions.
# Win probability moves when someone dies, and a lost duel *is* the death.
FEATURES = [
    "tier_id",
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

CATEGORICAL = ["map_id", "round_type_id", "tier_id"]

# Label: did the CT side win this round. T-side WP is 1 - p.
LABEL = "ct_won"

ROUND_SECONDS = 115.0      # competitive round timer
PLANT_SECONDS = 40.0       # post-plant timer

MAPS = ["de_mirage", "de_inferno", "de_nuke", "de_ancient",
        "de_dust2", "de_anubis", "de_train", "de_overpass"]
MAP_IDS = {m: i for i, m in enumerate(MAPS)}

ROUND_TYPES = ["pistol", "eco", "force", "full"]
ROUND_TYPE_IDS = {r: i for i, r in enumerate(ROUND_TYPES)}

# Skill tiers. These are not arbitrary buckets — they are the customer
# segments, which is why they are worth conditioning on. The same 4v2 retake
# is a very different proposition in tier-1 CS than in solo-queue Premier, and
# a model that averages them is wrong for everybody. Conditioning on tier means
# one model serves all four populations honestly instead of serving none.
TIERS = ["pro", "collegiate", "league", "premier"]
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
