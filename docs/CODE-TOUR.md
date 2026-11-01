# Code tour

A file-by-file walk through this repository: what each thing is, why it
exists, and what to read first.

If you have fifteen minutes, read `src/coursework/geometry/junctions.py`,
then `tests/oracle.py`, then run `coursework ui --demo-plan`. Everything else
is scaffolding around those two ideas.

---

## What the project is

A desktop tool that reads masonry quantities off a building plan. You trace
the walls, say what each one is made of, and it tells you how many blocks,
how many bricks, how many bags of mortar.

The part that makes it more than a calculator is what happens where two walls
meet. Masonry is measured along wall centerlines, and that convention is
exactly self-correcting at an L corner and self-correcting nowhere else. The
solver classifies every junction and corrects each one, and the report shows
both numbers: what the raw centerline total claims, and what it actually is.

---

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

coursework ui --demo-plan     # the app, traced over the sample drawing
coursework ui                 # the app, no underlay
coursework report --demo      # the takeoff as text
coursework export --demo -o takeoff.csv
coursework save-demo job.ctk  # write the demo to a project file
coursework bench              # junction detection benchmark
pytest -q                     # 177 tests
ruff check src tests tools    # lint
```

---

## The map

```
src/coursework/
  model/        plain data. No Qt, no geometry library, no database.
  geometry/     the junction solver. Pure Python and NumPy.
  quantities/   materials, arithmetic, report rendering.
  store/        SQLite project file with migrations.
  ui/           PySide6. The only package allowed to import Qt.
  demo.py       the sample building
  cli.py        command line entry point
  bench.py      performance benchmark
tools/          sample plan generator (dev only, not shipped)
tests/          177 tests including the independent oracle
docs/           decisions, this tour, images
assets/         the sample floor plan PDF
.github/        CI
```

The layering rule is **nothing outside `ui/` imports Qt**, and it is enforced
by a test, not by discipline. That is what lets the engine run headless:
testable in CI with no display, benchmarkable in a loop, drivable from a
command line.

---

## `src/coursework/model/` — the data

No behaviour beyond validation. Everything else in the project operates on
these objects.

### `types.py` (168 lines)

The dataclasses.

- **`Assembly`** — one masonry material at one nominal thickness. Carries
  `thickness_in`, `units_per_sf`, `mortar_bags_per_100_units`, and a
  `priority` that breaks ownership ties at junctions. Structural block
  outranks veneer because the block runs continuous through a junction and
  the veneer stops against it.
- **`Wall`** — a centerline polyline (`vertices`), an assembly key, a height.
  `segments` and `centerline_length_ft` are computed. Rejects fewer than two
  vertices or a non-positive height at construction.
- **`Opening`** — a rectangular hole on one wall. Stored as a **station**
  (distance along the wall centerline) rather than an absolute point, so the
  opening travels with the wall when it is edited.
- **`TakeoffSettings`** — the estimating rules the user is allowed to
  disagree with: `waste_factor`, `min_deduct_area_sf`, `sand_cy_per_bag`.
- **`Project`** — everything that gets saved: name, plan path, `px_per_ft`,
  walls, openings, settings.

**Internal units are decimal feet everywhere.** Thickness is quoted in inches
because that is the trade convention, and converted once. One unit internally
removes a whole class of bug that estimating tools are famous for.

### `units.py` (112 lines)

Feet-and-inches parsing and formatting, the only place that boundary exists.

`parse_ft_in` accepts what an estimator would actually type: `20'-6"`,
`20' 6 1/2"`, `20-6`, `20.5`, `6"`, `20ft 6in`, and curly quotes.
`format_ft_in` renders decimal feet back, rounded to 1/16" by default.

A bare number is read as feet, because that is what someone typing a wall
length means. A bare number with an inch mark is read as inches.

---

## `src/coursework/geometry/` — the heart

### `primitives.py` (105 lines)

Small 2D helpers: dot, cross, distance, point-to-segment distance, polyline
length, and `segment_intersection`.

`segment_intersection` returns the point **and both parameters** `t` and `u`.
Those parameters are what the junction classifier runs on: whether an
intersection lands at a wall's end or in its body is the difference between
an L corner and a T intersection.

Collinear overlap deliberately returns `None`. Two walls lying on top of each
other is a tracing error, not a junction, and the solver reports it rather
than inventing a correction.

`TOL = 0.02` feet, just under a quarter inch. Finer than anyone can trace on
a scanned plan, coarse enough to absorb float noise from the pixel-to-feet
conversion.

### `junctions.py` (495 lines) — read this one

The largest and most important file. Its module docstring contains the
derivation.

**The maths.** Wall A along +x with thickness `ta`, wall B along +y with
thickness `tb`, both ending at the origin:

```
overlap   x in [0,  tb/2],  y in [0,  ta/2]    area = ta*tb/4   counted twice
notch     x in [-tb/2, 0],  y in [-ta/2, 0]    area = ta*tb/4   counted zero times
```

Equal for any pair of thicknesses, so they cancel. That is why centerline
measurement works at corners.

**What the file contains, in order:**

- `ContactType` (END / BODY) and `JunctionKind` (L / T / X / MULTI)
- `Contact`, `Junction`, `Solution` dataclasses
- `_segments` — flattens walls into segments carrying their station offset
- `naive_pairs` — every cross-wall segment pair, O(n²), the obvious version
- `grid_pairs` — a uniform grid hash over bounding boxes
- `find_junctions` — intersects candidate pairs, classifies each contact as
  END or BODY, detects collinear overlap
- `_cluster` — groups pairwise hits at the same point into one node. **This
  is where the time actually goes on a large plan**; both a quadratic and a
  spatially hashed version are kept so the benchmark can compare and the
  tests can assert they agree
- `_classify` — two ENDs is an L, one END is a T, zero is an X, three or more
  contacts is MULTI
- `_pick_owner` — highest assembly priority wins, lowest wall id breaks ties
  so the answer never depends on drawing order
- `_apply` — the corrections, one branch per junction kind
- `solve` — the public entry point

**The corrections:**

| Junction | Correction |
|---|---|
| L, same assembly | none; overlap and notch cancel |
| L, mixed assembly | non-owner loses `t_owner/4`, owner gains `t_other/4` |
| T intersection | butting wall loses `t_host/2` |
| X crossing | non-owner loses `t_owner` |
| MULTI | pairwise against the owner, and flagged `needs_review` |

MULTI is the honest limit. Three or more walls at one point get an
approximation and say so in the report warnings, rather than quietly
returning a number.

---

## `src/coursework/quantities/` — from geometry to a bill

### `catalog.py` (95 lines)

The four assemblies (6", 8", 12" CMU and 4" brick veneer) and the published
constants behind them, with sources named in the docstring.

1.125 units per square foot for all three block sizes, because they present
the same 8x16 face. 6.75 for modular brick. 3 bags of mortar per 100 block,
7 per 1000 brick, 1 CY sand per 7 bags, from the Titan America guide. 5%
waste by default.

Thicknesses are **actual, not nominal**: an 8" block is 7-5/8" of material.
Using nominal would overstate every junction correction by about 5%.

The docstring also records that sources disagree on mortar, and why the
Titan figures are the default, rather than picking one silently.

### `takeoff.py` (182 lines)

The arithmetic chain, deliberately short so every step is reportable:

```
centerline length
  - junction corrections        -> net length
  x wall height                 -> gross face area
  - openings over the threshold -> net face area
  x units per sf                -> unit count
  x (1 + waste)                 -> ordered count
  -> mortar bags -> sand
```

`WallLine` is one row. `MaterialTotal` aggregates per assembly. `Report`
carries both the corrected number and `total_naive_area_sf`, the number an
uncorrected takeoff would have produced, which is what lets the report show
the difference.

### `render.py` (183 lines)

`as_text` for the terminal and the app's report panel, `as_csv` for Excel.

The CSV includes a per-junction table with coordinates, owner and note, so a
reviewer can audit every correction rather than trusting the total.

---

## `src/coursework/store/` — persistence

### `sqlite_store.py` (208 lines)

A takeoff is saved as a single SQLite file with the extension `.ctk`.

Tables: `meta`, `project`, `wall`, `wall_vertex`, `opening`. Foreign keys with
`ON DELETE CASCADE` so an opening cannot outlive its wall. `CHECK`
constraints on geometry. A `MIGRATIONS` list where each entry runs once, with
`schema_version` in `meta` recording progress, so a file written by an older
build opens in a newer one.

The whole save is one transaction. A constraint violation rolls back and
leaves the previous file intact, and there is a test for exactly that,
because it is someone's afternoon of work.

Why not JSON: a takeoff is a document, but it is also a thing people query.
"Every opening over 20 sf", "every wall of 12-inch block" are one line of SQL
and a page of Python over parsed JSON. Full reasoning in
[DECISIONS.md](DECISIONS.md) ADR 3.

---

## `src/coursework/ui/` — the only Qt

### `theme.py` (54 lines)

Colours and fonts in one place. Paper-coloured canvas rather than a dark IDE,
because estimators work from printed and scanned drawings. Junction dot
colours carry meaning: green for a corner that needed nothing, amber for one
that moved material, red for a crossing, purple for multi-way.

### `canvas.py` (437 lines)

The drawing surface: a `QGraphicsView` with a custom `drawBackground` for the
plan underlay and grid, and `drawForeground` for walls, openings and junction
dots.

Scene coordinates are plan-image pixels; the model stores feet; `px_per_ft` is
the only thing that converts, deliberately in one place.

**Walls are stroked at their real thickness** with flat caps and mitre joins,
not drawn as hairlines. That is how masonry actually meets, and it is why you
can see the overlap at a junction.

Modes: SELECT, CALIBRATE, DRAW_WALL. Pan with shift-drag or middle mouse,
zoom with the wheel. Clicking picks junctions before walls, because a
junction dot is what you click when you want to know why a number moved.

There is a comment in `to_scene` explaining a bug worth knowing about: the
obvious way to make plan y point up is `view.scale(1, -1)`, and that also
mirrors the background image so every loaded plan renders upside down. The
fix is to negate y at the single conversion boundary instead.

### `panels.py` (215 lines)

`WallPanel` edits the selected wall and shows its gross length, junction
adjustment, net length, area and unit count. `RulesPanel` exposes the waste
factor and the opening deduction threshold, so the estimating assumptions are
visible and editable rather than buried. `ReportPanel` is the live takeoff.
`JunctionLegend` explains the dot colours.

### `app.py` (368 lines)

`MainWindow`: toolbar, menus, docks, and the edit-to-report loop.

Every edit re-runs the entire takeoff. A 220-wall plan solves in about 7 ms,
so a dependency graph would be more code, more state, and a new class of bug
where the screen disagrees with the model.

`_on_junction_clicked` is the feature worth demoing: click a dot and the
status bar says what that junction did and why, in the same words the report
uses.

PDF loading rasterises page one with pymupdf at 150 dpi.

---

## Top-level modules

### `demo.py` (83 lines)

A 60x40 masonry shell built to exercise every junction type: four L corners
(two of them mixed-assembly, because the east wall is 12" block), four T
intersections, two materials, and openings both over and under the deduction
threshold. Plus a freestanding brick screen wall, because masonry contractors
bid those and it puts a second material in the bill without inventing a
strange cavity detail.

`demo_project_on_plan()` translates the same building onto the rendered
sample drawing so the overlay lines up without anyone tracing it by hand. The
offset is derived from the generator's constants, not measured by eye, so the
two stay in step.

### `cli.py` (100 lines)

`report`, `export`, `save-demo`, `bench`, `ui`. The CLI is not a side
feature; it is the proof that Qt really is confined to `ui/`.

### `bench.py` (190 lines)

Two generators (`lattice`, where every wall spans the plan, and `rooms`,
short wall runs) and a timing harness that reports both stages separately.

The benchmark exists partly to record a mistake: the pair scan looked like
the bottleneck and was not. Profiling showed 3 ms in intersection testing
against 229 ms in clustering. Both implementations are kept so the numbers
can be shown.

---

## `tools/make_demo_plan.py` (158 lines)

Generates `assets/demo_plan.pdf` with pymupdf: walls as double lines with
gaps and jambs at the openings, dimension strings with ticks, suite labels, a
title block and a scale note. Drawn at 1/8" = 1'-0", which is 9 points per
foot on letter landscape.

It is a development tool, not part of the installed package. Regenerate with:

```bash
python tools/make_demo_plan.py assets/demo_plan.pdf
```

---

## `tests/` — 177 tests

| File | What it covers |
|---|---|
| `oracle.py` | Not a test. The independent shapely oracle other tests use |
| `plans.py` | Synthetic plan generators shared by several suites |
| `conftest.py` | Sets `QT_QPA_PLATFORM=offscreen` before Qt is imported |
| `test_known_answers.py` | 14 hand-computable cases, arithmetic in each docstring |
| `test_oracle.py` | 46 tests comparing the solver to the polygon oracle |
| `test_properties.py` | Translation, rotation, ordering, reversal, scaling invariance; index vs naive agreement |
| `test_takeoff.py` | Quantity arithmetic against textbook figures |
| `test_units.py` | 30 parse and format cases |
| `test_store.py` | Round trips, migrations, cascade deletes, failed-save rollback |
| `test_ui.py` | The window driven headlessly |
| `test_layering.py` | Parses every module's AST; fails if Qt escapes `ui/` or shapely reaches `src/` |
| `test_end_to_end.py` | Renders the sample PDF, calibrates off its printed dimension, checks the recovered scale |

### The oracle, which is the point

`tests/oracle.py` merges every wall centerline into connected linework and
lets shapely buffer it by half the thickness with mitred joins, then measures
the polygon's area.

It shares no code and no reasoning with the solver. It does not know what a T
intersection is. They agree to one part in 10⁹ across closed shells, 25
randomly generated buildings, all four thicknesses, and n×n lattices of
nothing but crossings.

Shapely is a **test-only** dependency and `test_layering.py` fails if it ever
appears under `src/`.

---

## `docs/` and `assets/`

- **`DECISIONS.md`** — six architecture decision records: analytic
  corrections vs polygon booleans, shapely as a test-only oracle, SQLite over
  JSON, the centerline tracing convention, Qt confined to `ui/`, and
  recomputing on every edit. Each has context, decision, trade-offs and
  consequences.
- **`CODE-TOUR.md`** — this file.
- **`assets/demo_plan.pdf`** — the generated sample drawing. Labelled
  "SAMPLE DRAWING - NOT A REAL PROJECT" in its title block, because it is
  synthetic and should not be mistaken for a client plan.

---

## The images

All three live in `docs/img/` and all three are generated, not hand-made.

### `demo_plan.png` (792 × 612 pt, 37 KB)

Page one of `assets/demo_plan.pdf` rasterised at 110 dpi. A floor plan in the
conventional style: walls as double lines, gaps with jambs where openings
are, dimension strings reading 60'-0" and 40'-0", four suite labels, a
freestanding screen wall off to the right, and a title block giving the scale
as 1/8" = 1'-0".

This is what the app loads as an underlay, and what the end-to-end test
calibrates against.

Regenerate:

```bash
python tools/make_demo_plan.py assets/demo_plan.pdf
python -c "import pymupdf; pymupdf.open('assets/demo_plan.pdf')[0].get_pixmap(dpi=110).save('docs/img/demo_plan.png')"
```

### `app.png` (1250 px wide, 65 KB)

The application with the demo building loaded and no plan underlay, so the
grid shows. On the left, the canvas: walls stroked at true thickness, blue
for block and red for the brick screen wall, white rectangles where openings
are, and coloured dots at every junction. On the right, the Properties dock
(Wall / Rules / Legend tabs) above the live Takeoff report.

### `app_plan.png` (1250 px wide, 65 KB)

The same building traced over the sample drawing. This is the more useful
image: the traced walls sit exactly on the drawn walls and the openings land
exactly in the drawn gaps, which is a visual proof that the scale
calibration maths is right.

Both screenshots are captured headlessly on Qt's offscreen platform, so they
can be regenerated on any machine including CI:

```bash
QT_QPA_PLATFORM=offscreen python - <<'PY'
import pymupdf
from pathlib import Path
from PySide6.QtWidgets import QApplication
from coursework.ui.app import MainWindow
from coursework.demo import demo_project_on_plan, PLAN_DPI

png = Path("docs/img/demo_plan.png").resolve()
with pymupdf.open("assets/demo_plan.pdf") as doc:
    doc[0].get_pixmap(dpi=PLAN_DPI).save(png)

app = QApplication([])

w = MainWindow(); w.resize(1680, 980); w.show()
w.project = demo_project_on_plan(str(png)); w._after_load()
for _ in range(8): app.processEvents()
w.view.fit()
for _ in range(8): app.processEvents()
w.grab().scaledToWidth(1250).save("docs/img/app_plan.png")

w2 = MainWindow(); w2.resize(1680, 980); w2.show()
for _ in range(8): app.processEvents()
w2.view.fit()
for _ in range(8): app.processEvents()
w2.grab().scaledToWidth(1250).save("docs/img/app.png")
PY
```

---

## `.github/workflows/ci.yml`

Two jobs. `test` runs ruff and pytest on Python 3.11, 3.12 and 3.13, with
`fail-fast: false` so one version failing still reports the others. It
installs Qt's runtime libraries explicitly, because without them Qt cannot
load even its offscreen platform plugin and you get a confusing plugin error
rather than a test failure. `benchmark` runs the junction benchmark so the
numbers stay honest.

---

## One request, traced end to end

What happens when you drag a wall in the app:

1. `canvas.py` handles the mouse event and converts scene pixels to feet
   through `to_feet`.
2. The wall's vertices change on the `Wall` dataclass in `model/types.py`.
3. `app.py:refresh()` calls `takeoff.build(project)`.
4. `takeoff.build` calls `junctions.solve`, which rebuilds the segment list,
   finds candidate pairs through the grid hash, intersects them, classifies
   each contact as END or BODY, clusters hits into nodes, and applies one
   correction per junction kind.
5. `takeoff.build` turns net lengths into areas, subtracts openings over the
   threshold, and aggregates per assembly through `catalog.py`.
6. `render.as_text` formats it and `ReportPanel` displays it.
7. `canvas.py` repaints with the new junction set.

About 7 ms for a 220-wall plan, which is why step 3 re-runs everything rather
than trying to be clever.
