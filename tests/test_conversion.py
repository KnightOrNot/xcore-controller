import json
from types import SimpleNamespace

import pytest
from xcore_dataset.integrity import inventory, write_json

from xcore_controller.conversion import ConversionScheduler


@pytest.mark.parametrize("outcome", ["published", "failed", "missing", "corrupt"])
def test_scheduler_confirms_own_publication_not_only_cli_exit(
    tmp_path, monkeypatch, outcome
):
    session = tmp_path / "raw" / "session"
    destination = tmp_path / "lerobot" / "session" / "rev-0001"
    destination.mkdir(parents=True)
    (destination / "payload").write_text("complete data")
    if outcome != "missing":
        write_json(destination / "READY.json", {"files": inventory(destination)})
    if outcome == "corrupt":
        (destination / "payload").write_text("changed data")
    job = {
        "job_id": "test-job",
        "state": "queued",
        "session": str(session),
        "dataset_id": "session",
        "revision": "rev-0001",
        "destination": str(destination),
        "error": None,
    }

    def run(command, **kwargs):
        assert "PYTHONPATH" not in kwargs["env"]
        if "queue" in command:
            return SimpleNamespace(
                returncode=0, stdout=json.dumps({"result": job}), stderr=""
            )
        job.update(
            state="failed" if outcome == "failed" else "ready",
            error="encoding failed" if outcome == "failed" else None,
        )
        write_json(tmp_path / "jobs" / "test-job.json", job)
        # The existing jobs CLI exits zero even when a job failed.
        return SimpleNamespace(
            returncode=0, stdout=json.dumps({"result": [job]}), stderr=""
        )

    (tmp_path / "jobs").mkdir()
    monkeypatch.setattr("xcore_controller.conversion.subprocess.run", run)
    scheduler = ConversionScheduler(
        python="dataset-python",
        dataset_root=tmp_path,
        data_root=tmp_path,
        env={"PYTHONPATH": "vendor311"},
    )
    scheduler.submit(session)
    scheduler._thread.join(2)
    assert not scheduler._thread.is_alive()
    last = scheduler.status()["last"]
    assert last["verified"] is (outcome == "published")
    assert last["state"] == ("ready" if outcome == "published" else "failed")
    if outcome == "published":
        assert last["path"] == str(destination)
    if outcome == "failed":
        assert "encoding failed" in last["error"]
