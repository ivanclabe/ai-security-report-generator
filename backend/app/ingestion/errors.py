"""Errors of the data-acquisition layer.

Messages are written for the operator reading them in the chat/form (Spanish,
say what to check) and never contain credentials -- only host names, status
codes and environment-variable names.
"""


class SourceError(Exception):
    """Base class for every failure talking to the alarm data source."""


class SourceConfigError(SourceError):
    """Required SOURCE_* settings are missing or invalid."""


class SourceAuthenticationError(SourceError):
    """The source rejected the credentials, or the session expired and could not be renewed."""


class SourceUnavailableError(SourceError):
    """The source could not be reached (network/VPN, wrong IP, timeout, TLS, 5xx)."""


class SourceFormatError(SourceError):
    """The source answered, but not with the data we asked for (HTML instead of CSV, wrong company, ...)."""
