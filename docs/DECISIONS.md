# Decision records

Short records of the choices that shaped this project, kept because the
reasoning is harder to recover later than the code is.

---

## ADR 1: Analytic junction corrections, not polygon booleans

**Status:** accepted

**Context.** Wall material has to stop being counted twice where walls meet.
The obvious implementation is to build each wall's plan rectangle, union them
all, and measure the result. Shapely does that in about five lines.

**Decision.** Compute per-junction length corrections analytically from the
junction type and the wall thicknesses. Keep the polygon union, but only in
the test suite, as an independent oracle.

**Why.**

- A union produces *one number*. An estimator needs per-wall and per-assembly
  numbers, because crews are assigned per wall and block and brick are
  separate purchase orders. Attributing a shared corner back out of a merged
  polygon is harder than never merging it.
- A union cannot answer the mixed-assembly question at all. The total area is
  already right there; what is wrong is the split, and a polygon has no
  opinion about which material owns a corner.
- The analytic path is explainable. The report can say "wall 6 butts into
  wall 1, removed half the host thickness, 3-13/16 inches". A boolean
  operation can only say the area changed.
- It keeps a geometry library out of production code.

**Trade-offs.** The analytic rules have to be derived correctly for each
junction type, and multi-way junctions are only approximated. The polygon
approach would have been robust to every topology without thought. That is
mitigated by testing against the polygon, not by trusting the derivation.

**Consequences.** Every junction type is a named case with a documented
derivation. Anything that is not one of those cases is flagged for review
rather than silently handled.

---

## ADR 2: Shapely is a test-only dependency

**Status:** accepted

**Context.** The analytic solver needs checking against something that is not
itself.

**Decision.** `tests/oracle.py` merges wall centerlines and buffers them with
mitred joins to measure the real plan polygon. Shapely is in the `dev` extra
only, and `tests/test_layering.py` fails if it ever appears under `src/`.

**Why.** Two independent methods agreeing is a much stronger guarantee than
one method plus confidence. The oracle shares no code and no reasoning with
the solver: it does not know what a T intersection is. It agrees to 1 part in
10^9 across shells, random buildings, every thickness and lattices of pure
crossings.

Buffering merged linework with mitre joins also reproduces the corner fill on
its own, which independently confirms the overlap-equals-notch derivation
rather than assuming it.

**Trade-offs.** The oracle only works for single-assembly plans, for the
reason in ADR 1. Mixed-assembly cases fall back to hand arithmetic with the
derivation written into the test docstring.

**Consequences.** Production code has no geometry dependency. The install for
a user is PySide6, NumPy and pymupdf.

---

## ADR 3: SQLite for the project file, not JSON

**Status:** accepted

**Context.** A takeoff needs to be saved. The obvious options were a JSON
document and an embedded database.

**Decision.** A single SQLite file with the extension `.ctk`, a `meta` table
carrying `schema_version`, and an ordered list of migrations that each run
once.

**Why.**

- A takeoff is a document, but it is also a thing people query. "Every opening
  over 20 sf", "every wall of 12 inch block", "what changed since the last
  revision" are one line of SQL and a page of Python over parsed JSON.
- Writes are transactional. A failed save leaves the previous state intact,
  which matters for a file someone has spent an afternoon on. There is a test
  for exactly that.
- Foreign keys with `ON DELETE CASCADE` make it structurally impossible to
  leave an opening attached to a deleted wall.
- `CHECK` constraints catch invalid geometry at the storage boundary as well
  as in the model.
- Migrations mean a file written by an older build opens in a newer one
  without the user knowing anything happened.

**Trade-offs.** Not human-readable or diffable, which JSON would have been.
Version control on a project file is worse. For a single-user document that
is an acceptable loss; `export` writes CSV when text is wanted.

**Consequences.** Schema changes append to `MIGRATIONS` and never edit an
existing entry.

---

## ADR 4: Walls are traced on the centerline

**Status:** accepted

**Context.** A wall could be described by its centerline, by one face, or by
its full outline.

**Decision.** Centerline polylines, with thickness as a property of the
assembly.

**Why.** It is the trade standard, so it matches what an estimator already
does and what a drawing already dimensions. It makes a wall one polyline
instead of a closed outline that has to stay consistent when thickness
changes. And it has the self-correcting property at L corners, which means the
common case needs no correction at all.

**Trade-offs.** It is a convention the tool depends on. If someone traces to a
wall *face* instead, the endpoint will not land on the host's centerline, no T
junction is detected, and no correction is applied. The tool cannot tell the
difference between that and a wall that genuinely stops short.

**Consequences.** This is documented in the junction module, and the
tolerance is 0.02 ft, just under a quarter inch: finer than anyone can trace
on a scanned plan, coarse enough to absorb float noise from the pixel-to-feet
conversion.

---

## ADR 5: Qt is confined to `ui/`

**Status:** accepted

**Context.** It is easy and tempting to let a GUI framework spread, usually
through one convenience import.

**Decision.** Only `coursework.ui` may import PySide6. `tests/test_layering.py`
parses the AST of every module under `src/` and fails if Qt appears outside
that package.

**Why.** It is what makes the geometry engine testable in CI without a
display, benchmarkable in a loop, and drivable from the command line. The CLI
is not a side feature, it is the proof that the separation holds.

**Trade-offs.** Some duplication at the boundary. The canvas converts feet to
scene pixels rather than storing a Qt type on the model, and the panels
rebuild their state from plain dataclasses.

**Consequences.** The UI tests still run as real widgets on Qt's offscreen
platform, so the wiring between an edit and the number it produces is covered
too. The rule is checked rather than trusted, because a rule nobody enforces
is a comment.

---

## ADR 6: Recompute the whole takeoff on every edit

**Status:** accepted

**Context.** Editing a wall changes junctions, which changes lengths, which
changes quantities. Incremental invalidation is the usual answer.

**Decision.** Re-solve everything on every change.

**Why.** A 220-wall plan solves in about 7 ms. A dependency graph would be
more code, more state, and a new class of bug where the screen disagrees with
the model. At this scale it buys nothing.

**Trade-offs.** It will not hold forever. A multi-storey job with thousands of
walls would need either incremental solving or a background worker.

**Consequences.** The report on screen is never stale. If plans get large
enough to matter, the fix is to re-solve off the UI thread before it is to
make the solver incremental, since the solve is already fast and the risk is
blocking the paint.
