"""Application-specific errors."""


class AgentWorklogError(Exception):
    """Base class for expected application failures."""


class ConfigurationError(AgentWorklogError):
    """Raised when configuration is invalid."""


class HarnessSourceError(AgentWorklogError):
    """Raised when a harness source cannot be queried."""


class SessionParseError(HarnessSourceError):
    """Raised when a harness session payload cannot be normalized."""


class ReportOutputError(AgentWorklogError):
    """Raised when a report cannot be written safely."""


class ReportAlreadyExistsError(ReportOutputError):
    """Raised when report generation would overwrite an existing file."""


class NoSessionsError(AgentWorklogError):
    """Raised when no session activity matches the requested period."""
