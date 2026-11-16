from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from app.conversion import core
from app.conversion.real_world_benchmark import BenchmarkCase, BenchmarkManifest


def _runner_module():
    script_path = (
        Path(__file__).parents[1] / "scripts" / "run_m7b_controlled_fidelity_experiment.py"
    )
    specification = spec_from_file_location("m7b_controlled_fidelity_experiment", script_path)
    assert specification is not None
    assert specification.loader is not None
    module = module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_single_case_rerun_does_not_replace_existing_complete_summary(
    monkeypatch, tmp_path: Path
) -> None:
    runner = _runner_module()
    cases = tuple(
        BenchmarkCase(
            case_id,
            tmp_path / f"{case_id}.glb",
            "a" * 64,
            "private test source",
            "offline test only",
            ("test",),
            core.Axis.Y,
            24,
        )
        for case_id in ("duck", "mansion", "realistic-man")
    )
    manifest = BenchmarkManifest(tmp_path / "manifest.json", "available", "test", cases)
    original_summary = '{"records": ["complete matrix"]}\n'
    (tmp_path / "summary.json").write_text(original_summary, encoding="utf-8")

    monkeypatch.setattr(runner, "load_manifest", lambda _: manifest)
    monkeypatch.setattr(runner, "verify_case_source", lambda _: b"duck")
    monkeypatch.setattr(
        runner,
        "_record_run",
        lambda *_args, **_kwargs: {
            "schemaVersion": runner.SCHEMA_VERSION,
            "caseId": "duck",
            "sourceEvidenceResolution": 2,
            "maxParts": 60,
            "status": "completed",
        },
    )

    result = runner.run_experiment(
        tmp_path / "manifest.json",
        tmp_path,
        case_id="duck",
        source_evidence_resolution=2,
        max_parts=60,
    )

    assert len(result["records"]) == 1
    assert (tmp_path / "summary.json").read_text(encoding="utf-8") == original_summary
    assert (tmp_path / "duck-e2-cap60.json").is_file()
