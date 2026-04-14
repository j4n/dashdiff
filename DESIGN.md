# Normalization design: functional equivalence in Grafana dashboard JSON

## The core question

For each array or field in a Grafana dashboard JSON, we ask:
**does the order of elements, or the presence of a value, have any functional
effect on what the dashboard renders or how it behaves?**

If the answer is no, we can sort or strip the field in *lenient* (default) mode
to suppress diff noise.  If the answer is yes, we must leave it alone in lenient
mode and only expose it in *strict* mode.

---

## Field-by-field classification

### Top-level scalar fields

| Field | Lenient | Strict | Rationale |
|---|---|---|---|
| `id` | strip | strip | DB-generated integer; meaningless outside the instance |
| `iteration` | strip | strip | Unix-ms timestamp written on every save; pure noise |
| `version` | strip | strip | Auto-incremented save counter; not a semantic property |
| `uid` | keep | keep | Stable identifier used in links and provisioning |
| `title` | keep | keep | Visible to users |
| `schemaVersion` | keep | keep | Affects how Grafana migrates the JSON on load |
| `timezone` | keep | keep | Changes how time axes render |
| `refresh` | keep | keep | Changes auto-refresh behaviour |
| `graphTooltip` | keep | keep | Changes crosshair/tooltip sharing |
| `editable` | keep | keep | Controls whether the dashboard can be edited in the UI |
| `style` | keep | keep | `dark` vs `light` theme |
| `fiscalYearStartMonth` | keep | keep | Affects time calculations |
| `liveNow` | keep | keep | Affects streaming behaviour |

### `tags` (array of strings)

Tags are a **set** — Grafana treats them as an unordered collection for
search/filtering.  The UI sorts them alphabetically when displaying them.

| Mode | Behaviour |
|---|---|
| Lenient | Sort alphabetically → `["prod", "service"]` always |
| Strict | Preserve document order |

### `panels` (array of objects)

Panel order in the JSON is determined by the order they were added, not their
visual position.  The visual position is encoded in `gridPos`.  Grafana renders
panels by `gridPos`, not by array index.

| Mode | Behaviour |
|---|---|
| Lenient | Sort by `(gridPos.y, gridPos.x, title)` |
| Strict | Preserve document order |

### `panels[*].targets` (array of query objects)

`refId` is the stable identity of a query within a panel.  The order in the
array does not affect which series are drawn; Grafana maps by `refId`.

| Mode | Behaviour |
|---|---|
| Lenient | Sort by `refId` |
| Strict | Preserve document order |

### `panels[*].transformations` (array of objects)

Transformations are a **pipeline** — order is significant.  Swapping two
transformations changes the output.

| Mode | Behaviour |
|---|---|
| Lenient | Preserve document order |
| Strict | Preserve document order |

### `panels[*].overrides` (array of field override objects)

Overrides are applied in order; later overrides win on the same field.
Order is therefore significant.

| Mode | Behaviour |
|---|---|
| Lenient | Preserve document order |
| Strict | Preserve document order |

### `templating.list` (array of variable objects)

Variable order affects the order they appear in the dropdown bar, but not
their functional values.  Each variable is uniquely identified by `name`.

| Mode | Behaviour |
|---|---|
| Lenient | Sort by `name` |
| Strict | Preserve document order |

### `templating.list[*].options` (array of `{text, value}` objects)

These are the cached option values for a variable.  They are re-fetched from
the data source on load; the stored order has no functional effect.

| Mode | Behaviour |
|---|---|
| Lenient | Sort by `value` |
| Strict | Preserve document order |

### `annotations.list` (array of annotation objects)

Annotations are identified by `name`.  Their order in the list affects the
order they appear in the annotations panel, but not their functional query
behaviour.

| Mode | Behaviour |
|---|---|
| Lenient | Sort by `name` |
| Strict | Preserve document order |

### `links` (array of dashboard link objects)

Links appear in the top-right link bar in the order they are defined.  Order
is therefore visible to the user and potentially intentional.

| Mode | Behaviour |
|---|---|
| Lenient | Preserve document order |
| Strict | Preserve document order |

### `null`-valued dict keys

Grafana sometimes emits `null` for optional fields that are simply absent in
other exports (e.g. `"datasource": null` vs the key being missing entirely).
Functionally these are equivalent: Grafana treats a missing key and a `null`
value identically.

| Mode | Behaviour |
|---|---|
| Lenient | Strip all `null`-valued keys recursively (null ≡ absent) |
| Strict | Preserve `null` values (null ≠ absent) |

Note: `null` elements *inside arrays* are preserved in both modes, because
array position is significant and removing an element would shift indices.

### `timepicker.refresh_intervals` (array of strings)

The order of refresh intervals defines the order in the dropdown.  This is
a UI preference but not a functional difference in monitoring terms.

| Mode | Behaviour |
|---|---|
| Lenient | Sort (natural string sort) |
| Strict | Preserve document order |

### `timepicker.quick_ranges` (array of objects)

Same reasoning as `refresh_intervals`.

| Mode | Behaviour |
|---|---|
| Lenient | Sort by `display` |
| Strict | Preserve document order |

---

## Summary: what lenient mode sorts that strict mode does not

| Array | Sort key |
|---|---|
| `tags` | alphabetical |
| `panels` | `(gridPos.y, gridPos.x, title)` |
| `panels[*].targets` | `refId` |
| `templating.list` | `name` |
| `templating.list[*].options` | `value` |
| `annotations.list` | `name` |
| `timepicker.refresh_intervals` | natural string |
| `timepicker.quick_ranges` | `display` |

Arrays **never sorted** in either mode (order is functionally significant):
`panels[*].transformations`, `panels[*].overrides`, `links`

## Null-vs-absent equivalence (lenient mode only)

In lenient mode, `null`-valued dict keys are stripped recursively before any
other normalisation step.  This means a dashboard exported with
`"datasource": null` and one where the `datasource` key is absent entirely
will produce identical normalised output and therefore no diff noise.
