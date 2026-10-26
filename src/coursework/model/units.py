"""Feet and inches, in and out.

Construction drawings are dimensioned in feet and inches, so the app has to
accept what an estimator would actually type. Internally everything is decimal
feet; this module is the only boundary where that is true.
"""

from __future__ import annotations

import re
from fractions import Fraction

#  20'-6 1/2"   20' 6.5"   20-6   20.5   6"   20ft 6in
_PATTERN = re.compile(
    r"""^\s*
    (?:(?P<feet>\d+(?:\.\d+)?)\s*(?:'|ft|feet|f)\s*)?      # feet, optional
    (?:-|\s)*
    (?:
        (?P<whole>\d+)\s+(?P<num>\d+)\s*/\s*(?P<den>\d+)   # 6 1/2
      | (?P<frac_num>\d+)\s*/\s*(?P<frac_den>\d+)          # 1/2
      | (?P<inches>\d+(?:\.\d+)?)                          # 6 or 6.5
    )?
    \s*(?P<inmark>"|''|in|inch|inches)?
    \s*$""",
    re.VERBOSE,
)


#  20-6  or  20-6 1/2  with no unit marks at all. On a drawing a hyphen
#  between two numbers always means feet and inches, so it is read that way
#  before the general pattern gets a chance to see "20" as feet on its own.
_BARE_FT_IN = re.compile(
    r"""^\s*(?P<feet>\d+)\s*-\s*
    (?:(?P<whole>\d+)\s+(?P<num>\d+)\s*/\s*(?P<den>\d+)
      |(?P<inches>\d+(?:\.\d+)?))
    \s*$""",
    re.VERBOSE,
)


class UnitParseError(ValueError):
    pass


def parse_ft_in(text: str) -> float:
    """Parse a dimension into decimal feet.

    Accepts ``20'-6"``, ``20' 6 1/2"``, ``20-6``, ``20.5``, ``6"``, ``20ft``.
    A bare number is read as feet, which is what someone typing a wall length
    means. A bare number with an inch mark is read as inches.
    """
    if text is None:
        raise UnitParseError("empty dimension")
    raw = text.strip().replace("’", "'").replace("”", '"')
    if not raw:
        raise UnitParseError("empty dimension")

    bare = _BARE_FT_IN.match(raw)
    if bare:
        inches = float(bare.group("inches") or 0.0)
        if bare.group("whole"):
            inches = float(bare.group("whole")) + float(
                Fraction(int(bare.group("num")), int(bare.group("den")))
            )
        return float(bare.group("feet")) + inches / 12.0

    m = _PATTERN.match(raw)
    if not m:
        raise UnitParseError(f"cannot read {text!r} as a dimension")

    feet = float(m.group("feet")) if m.group("feet") else 0.0

    inches = 0.0
    if m.group("whole"):
        inches = float(m.group("whole")) + float(
            Fraction(int(m.group("num")), int(m.group("den")))
        )
    elif m.group("frac_num"):
        inches = float(Fraction(int(m.group("frac_num")), int(m.group("frac_den"))))
    elif m.group("inches"):
        inches = float(m.group("inches"))

    # "20.5" with no marks at all is feet, not inches.
    if not m.group("feet") and not m.group("inmark") and m.group("inches"):
        if m.group("whole") is None and m.group("frac_num") is None:
            return float(m.group("inches"))

    if feet == 0.0 and inches == 0.0:
        raise UnitParseError(f"cannot read {text!r} as a dimension")

    return feet + inches / 12.0


def format_ft_in(value_ft: float, *, precision: int = 16) -> str:
    """Render decimal feet as feet and inches, rounded to 1/16" by default."""
    sign = "-" if value_ft < 0 else ""
    total_in = round(abs(value_ft) * 12.0 * precision) / precision
    feet = int(total_in // 12)
    inches = total_in - feet * 12

    whole = int(inches)
    frac = Fraction(inches - whole).limit_denominator(precision)
    if frac == 1:
        whole += 1
        frac = Fraction(0)

    if frac:
        fraction = f"{frac.numerator}/{frac.denominator}"
        inch_text = f'{whole} {fraction}"' if whole else f'{fraction}"'
    else:
        inch_text = f'{whole}"'
    return f"{sign}{feet}'-{inch_text}"
