from agent_worklog.extraction.pipeline import EVIDENCE_TEXT_MAX_LENGTH
from agent_worklog.models.evidence import RepositoryEvidence, SessionEvidence
from agent_worklog.models.report import SessionRef
from agent_worklog.summarizers.base import session_directories, session_refs


def _evidence(*sessions: SessionEvidence) -> RepositoryEvidence:
    return RepositoryEvidence(
        repository_id="git:github.com/mike/agent-worklog",
        display_name="Agent Worklog",
        sessions=list(sessions),
    )


def test_session_refs_carries_session_id_and_title_in_order() -> None:
    evidence = _evidence(
        SessionEvidence(session_id="s1", repository_id="repo", title="Fix the exporter"),
        SessionEvidence(session_id="s2", repository_id="repo"),
    )

    assert session_refs(evidence) == [
        SessionRef(session_id="s1", title="Fix the exporter"),
        SessionRef(session_id="s2", title=None),
    ]


def test_session_refs_normalizes_free_text_titles_to_one_line() -> None:
    evidence = _evidence(
        SessionEvidence(
            session_id="s1",
            repository_id="repo",
            title="Fix the exporter\n```\n- injected list item",
        ),
        SessionEvidence(session_id="s2", repository_id="repo", title="  \n  "),
    )

    assert session_refs(evidence) == [
        SessionRef(session_id="s1", title="Fix the exporter ``` - injected list item"),
        SessionRef(session_id="s2", title=None),
    ]


def test_session_refs_caps_titles_at_the_evidence_text_length() -> None:
    """A harness-recorded title has no length bound of its own — Codex's
    `threads.title` is the verbatim first user message, and one measured on a
    real machine ran to 1,478 characters. It must not bypass the 300-character
    budget that applies to every other piece of evidence text.
    """

    long_title = "word " * 100  # far past EVIDENCE_TEXT_MAX_LENGTH once collapsed
    evidence = _evidence(
        SessionEvidence(session_id="s1", repository_id="repo", title=long_title)
    )

    [ref] = session_refs(evidence)

    assert ref.title is not None
    assert len(ref.title) == EVIDENCE_TEXT_MAX_LENGTH
    assert ref.title.endswith("…")


def test_session_directories_deduplicates_sorts_and_skips_blank() -> None:
    evidence = _evidence(
        SessionEvidence(session_id="s1", repository_id="repo", working_directory="/worktrees/b"),
        SessionEvidence(session_id="s2", repository_id="repo", working_directory="/worktrees/a"),
        SessionEvidence(session_id="s3", repository_id="repo", working_directory="/worktrees/b"),
        SessionEvidence(session_id="s4", repository_id="repo", working_directory="   "),
        SessionEvidence(session_id="s5", repository_id="repo"),
    )

    assert session_directories(evidence) == ["/worktrees/a", "/worktrees/b"]
