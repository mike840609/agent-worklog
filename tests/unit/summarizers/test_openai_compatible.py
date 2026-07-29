import json

import httpx

from agent_worklog.models.evidence import (
    EvidenceConfidence,
    EvidenceItem,
    EvidenceStatus,
    RepositoryEvidence,
    SessionEvidence,
)
from agent_worklog.models.report import SessionRef
from agent_worklog.summarizers.openai_compatible import OpenAICompatibleSummarizer
from agent_worklog.summarizers.rule_based import RuleBasedSummarizer


def repository_evidence() -> RepositoryEvidence:
    return RepositoryEvidence(
        repository_id="git:github.com/mike/agent-worklog",
        display_name="Agent Worklog",
        normalized_remote="github.com/mike/agent-worklog",
        branches=["main"],
        sessions=[
            SessionEvidence(
                session_id="s1",
                repository_id="git:github.com/mike/agent-worklog",
                title="Fix the exporter",
                working_directory="/repos/agent-worklog",
                goals=[
                    EvidenceItem(
                        text="Add report",
                        source_activity_ids=["a1"],
                        confidence=EvidenceConfidence.HIGH,
                        extraction_method="user_message",
                        status=EvidenceStatus.IN_PROGRESS,
                    )
                ],
                outcomes=[
                    EvidenceItem(
                        text="Tests passed",
                        source_activity_ids=["a2"],
                        confidence=EvidenceConfidence.HIGH,
                        extraction_method="successful_verification_command",
                        status=EvidenceStatus.COMPLETED,
                    )
                ],
            )
        ],
    )


class CaptureTransport:
    def __init__(self, contents: list[str]) -> None:
        self.contents = contents
        self.calls = 0
        self.last_json: dict[str, object] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.last_json = json.loads(request.content)
        content = self.contents[min(self.calls, len(self.contents) - 1)]
        self.calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )


def test_llm_payload_contains_evidence_not_raw_transcript() -> None:
    transport = CaptureTransport(
        [
            json.dumps(
                {
                    "summary": "Implemented reporting.",
                    "completed": ["Tests passed"],
                    "problems_resolved": [],
                    "in_progress": ["Add report"],
                    "key_files": [],
                }
            )
        ]
    )
    client = httpx.Client(
        base_url="https://example.test/v1",
        transport=httpx.MockTransport(transport.handler),
    )
    summarizer = OpenAICompatibleSummarizer(
        client=client,
        model="test-model",
        api_key="test-key",
        fallback=RuleBasedSummarizer(),
    )

    summary = summarizer.summarize(repository_evidence())

    assert summary.summary == "Implemented reporting."
    assert transport.last_json is not None
    serialized = str(transport.last_json)
    assert "source_activity_ids" in serialized
    assert "raw_metadata" not in serialized
    assert '"messages": []' not in serialized
    # Session identifiers and directories must come from evidence, never the LLM response:
    # the structured JSON above carries no "sessions"/"directories" keys at all.
    assert summary.sessions == [SessionRef(session_id="s1", title="Fix the exporter")]
    assert summary.directories == ["/repos/agent-worklog"]


def test_invalid_llm_json_retries_once_then_falls_back() -> None:
    transport = CaptureTransport(["not-json", "still-not-json"])
    client = httpx.Client(
        base_url="https://example.test/v1",
        transport=httpx.MockTransport(transport.handler),
    )
    summarizer = OpenAICompatibleSummarizer(
        client=client,
        model="test-model",
        api_key="test-key",
        fallback=RuleBasedSummarizer(),
    )

    summary = summarizer.summarize(repository_evidence())

    assert summary.completed == ["Tests passed"]
    assert transport.calls == 2
    assert any("LLM" in warning for warning in summarizer.drain_warnings())


def test_429_retries_and_uses_second_response() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "Recovered.",
                                    "completed": ["Tests passed"],
                                    "problems_resolved": [],
                                    "in_progress": [],
                                    "key_files": [],
                                }
                            )
                        }
                    }
                ]
            },
        )

    client = httpx.Client(
        base_url="https://example.test/v1",
        transport=httpx.MockTransport(handler),
    )
    summarizer = OpenAICompatibleSummarizer(
        client=client,
        model="test-model",
        api_key="test-key",
        fallback=RuleBasedSummarizer(),
    )

    assert summarizer.summarize(repository_evidence()).summary == "Recovered."
    assert calls == 2
