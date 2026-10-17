from pathlib import Path

import yaml

_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def test_ci_workflow_runs_once_per_commit():
    workflow = yaml.safe_load(_WORKFLOW.read_text())
    trigger = workflow[True]

    assert trigger["push"]["branches"] == ["main"]
    assert "pull_request" in trigger
    assert workflow["concurrency"]["cancel-in-progress"] is True
    assert (
        workflow["concurrency"]["group"]
        == "ci-${{ github.workflow }}-${{ github.ref }}"
    )
