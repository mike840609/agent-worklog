"""Application configuration models."""

from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OpenCodeCliSettings(BaseModel):
    """OpenCode executable invocation settings."""

    executable: str = "opencode"
    timeout_seconds: float = 30.0


class OpenCodeSettings(BaseModel):
    """OpenCode harness settings."""

    enabled: bool = True
    source: str = "cli"
    cli: OpenCodeCliSettings = Field(default_factory=OpenCodeCliSettings)


class ClaudeCodeSettings(BaseModel):
    """Claude Code harness settings."""

    enabled: bool = True
    projects_directory: Path = Field(
        default_factory=lambda: Path.home() / ".claude" / "projects"
    )


class HarnessSettings(BaseModel):
    """Configured coding-agent harnesses."""

    opencode: OpenCodeSettings = Field(default_factory=OpenCodeSettings)
    claude_code: ClaudeCodeSettings = Field(default_factory=ClaudeCodeSettings)


class ReportSettings(BaseModel):
    """Report defaults."""

    timezone: str = "Asia/Taipei"
    output_directory: Path = Path("reports")


class LlmSettings(BaseModel):
    """Optional OpenAI-compatible summarization settings."""

    enabled: bool = True
    provider: str = "openai-compatible"
    model: str = "gpt-5-mini"
    base_url: str = "https://api.openai.com/v1/"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: float = 60.0


class AppSettings(BaseSettings):
    """Top-level Agent Worklog settings."""

    model_config = SettingsConfigDict(
        env_prefix="AGENT_WORKLOG_",
        env_nested_delimiter="__",
    )

    harnesses: HarnessSettings = Field(default_factory=HarnessSettings)
    report: ReportSettings = Field(default_factory=ReportSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)
