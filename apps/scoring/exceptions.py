class ImmutableRecordError(Exception):
    """Raised when code attempts to mutate an append-only record after creation."""
