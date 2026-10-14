"""End-to-end: the normalize and diff subcommands on v2 dashboard files."""

import json

import pytest
from v2_helpers import element, v2_dashboard

from dashdiff.cli import main


def write(path, dashboard):
    path.write_text(json.dumps(dashboard), encoding="utf-8")
    return str(path)


def dashboard(expr="up", generation=1):
    el = element("P", "A")
    el["spec"]["data"]["spec"]["queries"][0]["spec"]["query"]["spec"]["expr"] = expr
    d = v2_dashboard(elements={"panel-1": el})
    d["metadata"]["generation"] = generation
    return d


class TestDiffV2:
    def test_save_counter_noise_is_no_diff(self, tmp_path, capsys):
        before = write(tmp_path / "a.json", dashboard(generation=4))
        after = write(tmp_path / "b.json", dashboard(generation=5))
        main(["diff", before, after])
        assert capsys.readouterr().out == ""

    def test_query_change_exits_one_and_shows_both_expressions(self, tmp_path, capsys):
        before = write(tmp_path / "a.json", dashboard(expr="up"))
        after = write(tmp_path / "b.json", dashboard(expr='up{job="x"}'))
        with pytest.raises(SystemExit) as exc:
            main(["diff", before, after])
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert '"expr": "up"' in out
        assert 'up{job=\\"x\\"}' in out


class TestNormalizeV2:
    def test_prints_normalized_json_without_noise(self, tmp_path, capsys):
        path = write(tmp_path / "a.json", dashboard(generation=9))
        main(["normalize", path])
        out = json.loads(capsys.readouterr().out)
        assert "generation" not in out["metadata"]
        assert out["metadata"]["name"] == "uid-1"
