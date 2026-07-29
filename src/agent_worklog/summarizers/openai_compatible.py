"""Optional evidence-grounded OpenAI-compatible repository summaries."""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from agent_worklog.models.evidence import RepositoryEvidence
from agent_worklog.models.report import RepositorySummary
from agent_worklog.summarizers.base import RepositorySummarizer
from agent_worklog.summarizers.rule_based import RuleBasedSummarizer


class _StructuredSummary(BaseModel):
    summary: str
    completed: list[str]
    problems_resolved: list[str]
    in_progress: list[str]
    key_files: list[str]


_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "summary",
        "completed",
        "problems_resolved",
        "in_progress",
        "key_files",
    ],
    "properties": {
        "summary": {"type": "string"},
        "completed": {"type": "array", "items": {"type": "string"}},
        "problems_resolved": {"type": "array", "items": {"type": "string"}},
        "in_progress": {"type": "array", "items": {"type": "string"}},
        "key_files": {"type": "array", "items": {"type": "string"}},
    },
}


class _RetryableSummaryError(Exception):
    pass


class OpenAICompatibleSummarizer(RepositorySummarizer):
    """Send only canonical evidence and fall back deterministically on failure."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        client: httpx.Client | None = None,
        base_url: str = "https://api.openai.com/v1/",
        timeout_seconds: float = 60.0,
        fallback: RepositorySummarizer | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            timeout=timeout_seconds,
        )
        self._fallback = fallback or RuleBasedSummarizer()
        self._warnings: list[str] = []

    def drain_warnings(self) -> list[str]:
        warnings = self._warnings[:]
        self._warnings.clear()
        return warnings

    def _payload(self, evidence: RepositoryEvidence) -> dict[str, object]:
        evidence_json = evidence.model_dump(mode="json")
        return {
            "model": self._model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Create a concise engineering worklog summary using only the "
                                "provided structured evidence. Do not infer unsupported completion."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(evidence_json, ensure_ascii=False),
                        }
                    ],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "repository_worklog_summary",
                    "strict": True,
                    "schema": _SCHEMA,
                }
            },
        }

    @staticmethod
    def _response_text(payload: Any) -> str:
        if not isinstance(payload, dict):
            raise _RetryableSummaryError("response is not a JSON object")
        output_text = payload.get("output_text")
        if isinstance(output_text, str):
            return output_text
        output = payload.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        return part["text"]
        choices = payload.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
        raise _RetryableSummaryError("response does not contain structured text")

    def _request(self, evidence: RepositoryEvidence) -> _StructuredSummary:
        try:
            response = self._client.post(
                "responses",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=self._payload(evidence),
            )
        except httpx.TimeoutException as exc:
            raise _RetryableSummaryError("request timed out") from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise _RetryableSummaryError(f"HTTP {response.status_code}")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"HTTP {response.status_code}") from exc
        try:
            structured = json.loads(self._response_text(response.json()))
            return _StructuredSummary.model_validate(structured)
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
            raise _RetryableSummaryError("invalid structured output") from exc

    def summarize(self, evidence: RepositoryEvidence) -> RepositorySummary:
        failure: Exception | None = None
        for attempt in range(2):
            try:
                result = self._request(evidence)
                return RepositorySummary(
                    repository_id=evidence.repository_id,
                    display_name=evidence.display_name,
                    normalized_remote=evidence.normalized_remote,
                    summary=result.summary,
                    completed=result.completed,
                    problems_resolved=result.problems_resolved,
                    in_progress=result.in_progress,
                    key_files=result.key_files,
                    session_count=len(evidence.sessions),
                    child_session_count=evidence.child_session_count,
                    branches=evidence.branches,
                )
            except _RetryableSummaryError as exc:
                failure = exc
                if attempt == 0:
                    continue
            except (httpx.HTTPError, RuntimeError) as exc:
                failure = exc
            break

        detail = str(failure) if failure is not None else "unknown error"
        self._warnings.append(
            f"LLM summary unavailable for {evidence.display_name}; "
            f"used deterministic fallback ({detail})"
        )
        return self._fallback.summarize(evidence)
