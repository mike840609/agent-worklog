from typer.testing import CliRunner

from agent_worklog.cli import app

runner = CliRunner()


def test_help_lists_core_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "doctor" in result.stdout
    assert "scan" in result.stdout
    assert "report" in result.stdout


def test_scan_rejects_an_unknown_harness() -> None:
    from typer.testing import CliRunner

    import agent_worklog.cli as cli

    result = CliRunner().invoke(cli.app, ["scan", "--days", "7", "--harness", "unknown"])

    assert result.exit_code == 2


def test_build_scan_service_selects_the_claude_code_source(tmp_path) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import agent_worklog.cli as cli
    from agent_worklog.config import AppSettings
    from agent_worklog.harnesses.claude_code.source import ClaudeCodeFileSource
    from agent_worklog.models.time_range import DateRange

    tz = ZoneInfo("Asia/Taipei")
    settings = AppSettings()
    settings.harnesses.claude_code.projects_directory = tmp_path
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=tz),
        until=datetime(2026, 7, 27, tzinfo=tz),
    )

    service = cli._build_scan_service(
        settings,
        period,
        harness=cli.Harness.CLAUDE_CODE,
    )

    assert isinstance(service._source, ClaudeCodeFileSource)


def test_build_scan_service_drops_sessions_from_a_configured_excluded_repository(
    tmp_path, monkeypatch
) -> None:
    """The exclude setting takes effect through `_build_scan_service`: a scan
    built from it omits the configured repository's sessions, rather than just
    wiring a private field that nothing observable depends on.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import agent_worklog.cli as cli
    from agent_worklog.config import AppSettings
    from agent_worklog.models.repository import (
        RepositoryIdentity,
        RepositoryIdentityType,
    )
    from agent_worklog.models.session import (
        ActivityType,
        AgentSession,
        SessionActivity,
        SessionDescriptor,
    )
    from agent_worklog.models.time_range import DateRange

    tz = ZoneInfo("Asia/Taipei")
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=tz),
        until=datetime(2026, 7, 27, tzinfo=tz),
    )

    def session(session_id: str, directory: str) -> AgentSession:
        return AgentSession(
            harness="claude-code",
            session_id=session_id,
            working_directory=directory,
            activities=[
                SessionActivity(
                    activity_id=session_id,
                    activity_type=ActivityType.USER_MESSAGE,
                    timestamp=datetime(2026, 7, 21, tzinfo=tz),
                    content="hi",
                )
            ],
        )

    sessions = {
        "dotfiles-1": session("dotfiles-1", "/tmp/dotfiles"),
        "notes-1": session("notes-1", "/tmp/notes"),
        "work-1": session("work-1", "/tmp/work"),
    }

    class StubSource:
        def discover(self, _period: DateRange) -> list[SessionDescriptor]:
            return [
                SessionDescriptor(harness="claude-code", session_id=session_id)
                for session_id in sessions
            ]

        def load(self, descriptor: SessionDescriptor) -> AgentSession:
            return sessions[descriptor.session_id]

    class StubResolver:
        def __init__(self, runner=None) -> None:
            self._runner = runner

        def resolve(self, agent_session: AgentSession) -> RepositoryIdentity:
            repository_name = agent_session.session_id.split("-", 1)[0]
            return RepositoryIdentity(
                repository_id=f"git:github.com/mike/{repository_name}",
                display_name=repository_name.capitalize(),
                identity_type=RepositoryIdentityType.GIT_REMOTE,
                resolution_method="stub",
            )

    def make_source(**kwargs) -> StubSource:
        return StubSource()

    monkeypatch.setattr(cli, "ClaudeCodeFileSource", make_source)
    monkeypatch.setattr(cli, "RepositoryResolver", StubResolver)

    settings = AppSettings()
    settings.report.exclude_repositories = "git:github.com/mike/dotfiles"
    settings.harnesses.claude_code.projects_directory = tmp_path

    service = cli._build_scan_service(
        settings,
        period,
        harness=cli.Harness.CLAUDE_CODE,
    )
    result = service.scan()

    assert [item.session.session_id for item in result.resolved_sessions] == [
        "notes-1",
        "work-1",
    ]
    assert result.excluded_session_count == 1
    assert result.loaded_session_count == 2
    assert any("Dotfiles" in warning for warning in result.warnings)


def test_build_report_service_carries_the_detail_level(tmp_path) -> None:
    """Closes a seam a mutation test found: deleting `detail=detail,` from the
    `ReportService(...)` call in `_build_report_service` left the full suite
    green, so `--detail brief` could silently become a no-op end to end.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import agent_worklog.cli as cli
    from agent_worklog.config import AppSettings
    from agent_worklog.models.time_range import DateRange
    from agent_worklog.renderers.markdown import DetailLevel

    tz = ZoneInfo("Asia/Taipei")
    settings = AppSettings()
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=tz),
        until=datetime(2026, 7, 27, tzinfo=tz),
    )

    service = cli._build_report_service(
        settings,
        period,
        tmp_path / "report.md",
        no_llm=True,
        now=datetime(2026, 7, 29, 20, 0, tzinfo=tz),
        detail=DetailLevel.BRIEF,
    )

    assert service._detail is DetailLevel.BRIEF


def test_a_disabled_harness_is_refused_with_a_configuration_error(tmp_path) -> None:
    """An off switch a privacy tool advertises has to actually turn something off."""

    import agent_worklog.cli as cli

    result = CliRunner().invoke(
        cli.app,
        ["scan", "--days", "7", "--harness", "claude-code"],
        env={"AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__ENABLED": "false"},
    )

    assert result.exit_code == 3
    assert "AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__ENABLED" in result.stdout


def test_doctor_refuses_a_disabled_harness() -> None:
    import agent_worklog.cli as cli

    result = CliRunner().invoke(
        cli.app,
        ["doctor", "--harness", "opencode"],
        env={"AGENT_WORKLOG_HARNESSES__OPENCODE__ENABLED": "false"},
    )

    assert result.exit_code == 3
    assert "disabled by configuration" in result.stdout


def test_report_still_runs_when_the_harness_is_enabled(tmp_path) -> None:
    import agent_worklog.cli as cli

    result = CliRunner().invoke(
        cli.app,
        ["scan", "--days", "7", "--harness", "claude-code"],
        env={
            "AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__ENABLED": "true",
            "AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY": str(tmp_path),
        },
    )

    assert result.exit_code == 4  # no sessions in an empty directory, not a config error


def test_no_sessions_message_only_claims_exclusion_when_it_is_the_whole_story() -> None:
    """A scan emptied by load failures must not be blamed on the config: the
    exclusion explanation is claimed only when exclusion removed every session
    and something else did not eat the rest.
    """
    import agent_worklog.cli as cli

    neutral = (
        (cli.Harness.OPENCODE, "no opencode activity found in the requested period"),
        (cli.Harness.CODEX, "no codex activity found in the requested period"),
    )
    excluded = (
        (
            cli.Harness.OPENCODE,
            "all opencode sessions in the requested period were excluded by configuration",
        ),
        (
            cli.Harness.CODEX,
            "all codex sessions in the requested period were excluded by configuration",
        ),
    )

    for harness, message in excluded:
        assert cli._no_sessions_message(harness, excluded=True, failed=False) == message
    for harness, message in neutral:
        assert cli._no_sessions_message(harness, excluded=False, failed=False) == message
        assert cli._no_sessions_message(harness, excluded=False, failed=True) == message
        assert cli._no_sessions_message(harness, excluded=True, failed=True) == message


def test_load_settings_reads_the_settings_file(monkeypatch, tmp_path) -> None:
    import agent_worklog.cli as cli

    path = tmp_path / "config.env"
    path.write_text("AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL='from-file'\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.delenv("AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL", raising=False)

    assert cli._load_settings().harnesses.opencode.cli.model == "from-file"


def test_the_environment_beats_the_settings_file(monkeypatch, tmp_path) -> None:
    """The file is a default store, not an override: an exported variable wins."""

    import agent_worklog.cli as cli

    path = tmp_path / "config.env"
    path.write_text("AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL='from-file'\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.setenv("AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL", "from-environment")

    assert cli._load_settings().harnesses.opencode.cli.model == "from-environment"


def test_load_settings_points_at_the_file_when_it_holds_a_bad_value(
    monkeypatch, tmp_path
) -> None:
    import pytest

    import agent_worklog.cli as cli
    from agent_worklog.errors import ConfigurationError

    path = tmp_path / "config.env"
    path.write_text(
        "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS='abc'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))

    with pytest.raises(ConfigurationError) as error:
        cli._load_settings()

    assert str(path) in str(error.value)


def test_load_settings_ignores_a_foreign_variable_in_the_settings_file(
    monkeypatch, tmp_path
) -> None:
    """A line another tool owns must not make every command reject the file.

    `DotEnvSettingsSource` sweeps every variable in the file into the model,
    unlike the environment source, which only reads names it owns — so a
    settings file shared with (or leftover from) another tool must not turn
    into a hard `extra_forbidden` failure.
    """

    import agent_worklog.cli as cli

    path = tmp_path / "config.env"
    path.write_text(
        "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL='gpt-5'\n"
        "OPENAI_API_KEY='sk-proj-not-a-real-secret-key'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.delenv("AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL", raising=False)

    settings = cli._load_settings()

    assert settings.harnesses.opencode.cli.model == "gpt-5"


def test_load_settings_does_not_echo_a_secret_looking_value_in_its_error(
    monkeypatch, tmp_path
) -> None:
    """A bad value in a setting the model DOES own still lands in the message.

    (a) alone (ignoring foreign variables) does not cover this: a malformed
    value for a setting the model owns, such as a base URL with an embedded
    password, still reaches pydantic's validation error text, and that text
    must not echo the secret verbatim.
    """

    import pytest

    import agent_worklog.cli as cli
    from agent_worklog.errors import ConfigurationError

    path = tmp_path / "config.env"
    path.write_text(
        "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS="
        "'sk-proj-not-a-real-secret-key'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))

    with pytest.raises(ConfigurationError) as error:
        cli._load_settings()

    assert "sk-proj-not-a-real-secret-key" not in str(error.value)
    assert "[REDACTED]" in str(error.value)
