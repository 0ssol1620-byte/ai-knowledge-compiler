"""Scanner summaries must not expose secret matches or free-form messages."""

import json

from scripts.summarize_trivy_sarif import summarize


def test_summary_preserves_finding_identity_without_sensitive_match(tmp_path):
    path = tmp_path / "scan.json"
    path.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "results": [
                            {
                                "ruleId": "synthetic-secret-rule",
                                "level": "error",
                                "message": {"text": "synthetic-sensitive-value"},
                                "locations": [
                                    {
                                        "physicalLocation": {
                                            "artifactLocation": {"uri": "fixture.env"}
                                        }
                                    }
                                ],
                                "partialFingerprints": {"secret": "synthetic-sensitive-value"},
                            }
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    summary = summarize(path)
    assert len(summary) == 1
    assert json.loads(summary[0]) == {
        "ruleId": "synthetic-secret-rule",
        "level": "error",
        "paths": ["fixture.env"],
    }
    assert "synthetic-sensitive-value" not in summary[0]
