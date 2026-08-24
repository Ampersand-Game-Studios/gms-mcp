from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_compatibility_matrix import build_evidence, main, render_matrix


def test_committed_compatibility_matrix_matches_generator() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    matrix_path = repo_root / "documentation" / "COMPATIBILITY_MATRIX.md"
    assert matrix_path.read_text(encoding="utf-8") == render_matrix()
    assert main(["--check", "--output", str(matrix_path)]) == 0


def test_evidence_is_explicit_about_declarations_and_ci_inputs(tmp_path: Path) -> None:
    output = tmp_path / "compatibility_evidence.json"
    assert (
        main(
            [
                "--evidence-output",
                str(output),
                "--executed-evidence",
                "pytest install parity",
                "--verified-as-of",
                "deadbeef",
            ]
        )
        == 0
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["verified_as_of"] == "deadbeef"
    assert payload["executed_evidence"] == ["pytest install parity"]
    assert "clients" in payload["declarations"]


def test_evidence_omits_verified_as_of_without_ci_input() -> None:
    evidence = build_evidence(executed_evidence=[], verified_as_of=None)
    assert "verified_as_of" not in evidence
