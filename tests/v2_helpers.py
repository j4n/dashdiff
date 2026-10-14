"""Builders for v2 dashboard test data."""


def v2_dashboard(**spec):
    """Build a minimal v2 envelope; *spec* keys override the spec defaults."""
    return {
        "apiVersion": "dashboard.grafana.app/v2",
        "kind": "Dashboard",
        "metadata": {"name": "uid-1"},
        "spec": {"title": "T", "elements": {}, "layout": {}, **spec},
    }


def ref(name):
    return {"kind": "ElementReference", "name": name}


def grid_item(name, x, y):
    return {
        "kind": "GridLayoutItem",
        "spec": {"x": x, "y": y, "width": 12, "height": 4, "element": ref(name)},
    }


def grid(*items):
    return {"kind": "GridLayout", "spec": {"items": list(items)}}


def auto_grid(*names):
    items = [{"kind": "AutoGridLayoutItem", "spec": {"element": ref(n)}} for n in names]
    return {"kind": "AutoGridLayout", "spec": {"maxColumnCount": 1, "items": items}}


def rows(*row_specs):
    """Each row spec is (title, layout)."""
    return {
        "kind": "RowsLayout",
        "spec": {
            "rows": [
                {"kind": "RowsLayoutRow", "spec": {"title": t, "layout": layout}}
                for t, layout in row_specs
            ]
        },
    }


def element(title, *ref_ids):
    queries = [
        {"kind": "PanelQuery", "spec": {"refId": r, "query": {"spec": {"expr": r}}}}
        for r in ref_ids
    ]
    return {
        "kind": "Panel",
        "spec": {
            "title": title,
            "vizConfig": {"kind": "timeseries", "spec": {}},
            "data": {"kind": "QueryGroup", "spec": {"queries": queries}},
        },
    }
