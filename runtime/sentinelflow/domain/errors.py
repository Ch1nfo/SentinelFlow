class SentinelFlowError(Exception):
    """Base exception for the SentinelFlow runtime."""


class SkillNotFoundError(SentinelFlowError):
    """Raised when a requested SentinelFlow skill does not exist."""


class SkillExecutionError(SentinelFlowError):
    """Raised when an executable SentinelFlow skill fails."""


class PolicyViolationError(SentinelFlowError):
    """Raised when an operation violates SentinelFlow runtime policies."""


class SkillConfigurationError(SentinelFlowError):
    """Raised when a SentinelFlow skill has invalid or incomplete configuration."""
