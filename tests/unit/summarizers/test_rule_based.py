from agent_worklog.models.evidence import (
    EvidenceConfidence,
    EvidenceItem,
    EvidenceStatus,
    RepositoryEvidence,
    SessionEvidence,
)
from agent_worklog.summarizers.rule_based import RuleBasedSummarizer


def item(text: str, status: EvidenceStatus, confidence: EvidenceConfidence) -> EvidenceItem:
    return EvidenceItem(
        text=text,
        source_activity_ids=[f"source:{text}"],
        confidence=confidence,
        extraction_method="test",
        status=status,
    )


def test_rule_summary_separates_completed_and_in_progress() -> None:
    evidence = RepositoryEvidence(
        repository_id="git:github.com/mike/agent-worklog",
        display_name="Agent Worklog",
        normalized_remote="github.com/mike/agent-worklog",
        branches=["main"],
        sessions=[
            SessionEvidence(
                session_id="s1",
                repository_id="git:github.com/mike/agent-worklog",
                goals=[item("Add cache", EvidenceStatus.IN_PROGRESS, EvidenceConfidence.HIGH)],
                outcomes=[
                    item("Tests passed", EvidenceStatus.COMPLETED, EvidenceConfidence.HIGH),
                    item("Claimed done", EvidenceStatus.UNKNOWN, EvidenceConfidence.LOW),
                ],
                files_changed=[
                    item("src/cache.py", EvidenceStatus.UNKNOWN, EvidenceConfidence.HIGH)
                ],
            )
        ],
    )

    summary = RuleBasedSummarizer().summarize(evidence)

    assert "Tests passed" in summary.completed
    assert "Add cache" in summary.in_progress
    assert "Claimed done" not in summary.completed
    assert summary.key_files == ["src/cache.py"]
    assert summary.session_count == 1


def test_rule_summary_limits_each_section_to_twenty_items() -> None:
    evidence = RepositoryEvidence(
        repository_id="repo",
        display_name="Repo",
        sessions=[
            SessionEvidence(
                session_id="s1",
                repository_id="repo",
                outcomes=[
                    item(
                        f"Completed {index:02d}",
                        EvidenceStatus.COMPLETED,
                        EvidenceConfidence.HIGH,
                    )
                    for index in range(22)
                ],
            )
        ],
    )

    summary = RuleBasedSummarizer().summarize(evidence)

    assert len(summary.completed) == 21
    assert summary.completed[-1] == "Additional items omitted: 2"


def test_medium_confidence_outcomes_are_reported_as_inferred() -> None:
    evidence = RepositoryEvidence(
        repository_id="git:github.com/mike/agent-worklog",
        display_name="Agent Worklog",
        sessions=[
            SessionEvidence(
                session_id="sess-1",
                repository_id="git:github.com/mike/agent-worklog",
                outcomes=[
                    EvidenceItem(
                        text="Verification passed: pytest -q",
                        source_activity_ids=["a-1"],
                        confidence=EvidenceConfidence.MEDIUM,
                        extraction_method="stderr_heuristic",
                        status=EvidenceStatus.COMPLETED,
                    ),
                    EvidenceItem(
                        text="Verification passed: ruff check .",
                        source_activity_ids=["a-2"],
                        confidence=EvidenceConfidence.HIGH,
                        extraction_method="successful_verification_command",
                        status=EvidenceStatus.COMPLETED,
                    ),
                ],
            )
        ],
    )

    summary = RuleBasedSummarizer().summarize(evidence)

    assert "Verification passed: pytest -q (inferred)" in summary.completed
    assert "Verification passed: ruff check ." in summary.completed


def test_low_confidence_outcomes_are_still_excluded() -> None:
    """Assistant self-claims stay out of the report; only stderr inference is promoted."""

    evidence = RepositoryEvidence(
        repository_id="git:github.com/mike/agent-worklog",
        display_name="Agent Worklog",
        sessions=[
            SessionEvidence(
                session_id="sess-1",
                repository_id="git:github.com/mike/agent-worklog",
                outcomes=[
                    EvidenceItem(
                        text="I implemented the retry",
                        source_activity_ids=["a-1"],
                        confidence=EvidenceConfidence.LOW,
                        extraction_method="assistant_claim",
                        status=EvidenceStatus.COMPLETED,
                    )
                ],
            )
        ],
    )

    summary = RuleBasedSummarizer().summarize(evidence)

    assert summary.completed == []
