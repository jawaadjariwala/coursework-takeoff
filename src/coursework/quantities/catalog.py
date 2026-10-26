"""Standard assemblies and the published constants behind them.

Every number here is a trade rule of thumb from a citable source, not
something invented for this project. They are defaults: a shop that buys
different units or runs a different joint can edit them, and the report prints
whatever was actually used.

Sources
-------
Units per square foot of wall face
    8x8x16 and 12x8x16 CMU lay up 1.125 units per sf with a 3/8" joint. Both
    sizes present the same 8"x16" face, so the per-sf rate does not change with
    wall thickness, only the material behind it does.
    Modular brick lays up 6.75 per sf with a 3/8" joint (NASCLA contractor
    study guide; other sources quote 6.86 from the raw formula, or 7 flat as a
    field rule).
Mortar
    3 bags per 100 block and 7 bags per 1000 brick, with 1 cubic yard of sand
    per 7 bags (Titan America Block Estimating Guide, which labels these
    "rule of thumb" figures). Sources disagree here: one calculator quotes 2.5
    bags per 100 block, and volume-based methods derived from joint thickness
    land higher. The Titan figures are the default because they come from a
    manufacturer and are stated on a consistent basis.
Waste
    5% to 10% added to all quantities for breakage, spillage and error is the
    standard allowance. 5% is the default here.

CMHA TEK 04-02A is worth noting alongside all of this: it warns that layouts
with numerous returns and corners significantly increase both the unit count
and the mortar volume. That is the same effect this tool measures from the
other direction, by refusing to double count the material at those corners.
"""

from __future__ import annotations

from ..model.types import Assembly, UnitType

#: Priority decides who owns shared material where two assemblies meet.
#: Structural block runs continuous through a junction and veneer stops
#: against it, so block outranks brick.
_STRUCTURAL = 100
_VENEER = 10

CATALOG: dict[str, Assembly] = {
    a.key: a
    for a in [
        Assembly(
            key="cmu8",
            label='8" CMU',
            thickness_in=7.625,
            unit_type=UnitType.CMU,
            units_per_sf=1.125,
            mortar_bags_per_100_units=3.0,
            priority=_STRUCTURAL,
        ),
        Assembly(
            key="cmu12",
            label='12" CMU',
            thickness_in=11.625,
            unit_type=UnitType.CMU,
            units_per_sf=1.125,
            mortar_bags_per_100_units=3.0,
            priority=_STRUCTURAL + 1,
        ),
        Assembly(
            key="cmu6",
            label='6" CMU',
            thickness_in=5.625,
            unit_type=UnitType.CMU,
            units_per_sf=1.125,
            mortar_bags_per_100_units=3.0,
            priority=_STRUCTURAL - 1,
        ),
        Assembly(
            key="brick4",
            label='4" Brick veneer',
            thickness_in=3.625,
            unit_type=UnitType.BRICK,
            units_per_sf=6.75,
            mortar_bags_per_100_units=0.7,  # 7 bags per 1000 brick
            priority=_VENEER,
        ),
    ]
}

DEFAULT_ASSEMBLY = "cmu8"


def get(key: str) -> Assembly:
    try:
        return CATALOG[key]
    except KeyError:
        raise KeyError(
            f"unknown assembly {key!r}; known: {sorted(CATALOG)}"
        ) from None
