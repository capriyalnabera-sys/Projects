import pytest

from scenarios import run_all

RESULTS = run_all()


@pytest.mark.parametrize("r", [r for r in RESULTS if r["status"] != "Phase 3"],
                         ids=lambda r: f"{r['no']:02d}-{r['check'][:40]}")
def test_scenario(r):
    assert r["status"] == "Pass", f"{r['scenario']} / {r['check']}: expected {r['expected']} actual {r['actual']}"
