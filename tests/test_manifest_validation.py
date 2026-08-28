"""Every committed manifest passes the activation gates, via the same code
path the CLI runs (the wired seam, not a parallel reimplementation)."""
from commonwealth.cli.__main__ import _validate_all
from commonwealth.runtime import load_context
from tests.conftest import ReplayFetcher, load_recording
from commonwealth.adapters.arcgis import ArcGISAdapter
from commonwealth.adapters.base import TTLCache


def test_all_committed_manifests_validate(capsys):
    ctx = load_context(arcgis=ArcGISAdapter(
        fetcher=ReplayFetcher(load_recording()["exchanges"]),
        cache=TTLCache()))
    rc = _validate_all(ctx)
    out = capsys.readouterr().out
    print(out)
    assert "checked 0 manifest" not in out, "zero manifests is a failure"
    assert rc == 0, out
