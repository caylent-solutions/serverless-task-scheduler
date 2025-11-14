"""
Validation utilities for URL-safe identifiers.

These validators ensure that user input is safe for use in URLs and API paths,
preventing URL injection attacks and ensuring consistent data format across
tenant IDs, target aliases, target IDs, and schedule IDs.
"""

import re


# Pattern for URL-safe identifiers: alphanumeric (upper and lowercase), underscores, and hyphens
URL_SAFE_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')

# Maximum length for identifiers (36 = UUID length)
MAX_IDENTIFIER_LENGTH = 36
MIN_IDENTIFIER_LENGTH = 1


def validate_url_safe_identifier(value: str, field_name: str = "identifier") -> str:
    """
    Validate that a string is URL-safe and raise ValueError if not.

    Args:
        value: The string to validate
        field_name: Name of the field for error messages

    Returns:
        The validated value

    Raises:
        ValueError: If the value is not URL-safe
    """
    if not value:
        raise ValueError(f"{field_name} is required")

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")

    if len(value) < MIN_IDENTIFIER_LENGTH:
        raise ValueError(
            f"{field_name} must be at least {MIN_IDENTIFIER_LENGTH} character long"
        )

    if len(value) > MAX_IDENTIFIER_LENGTH:
        raise ValueError(
            f"{field_name} must be less than {MAX_IDENTIFIER_LENGTH} characters"
        )

    if not URL_SAFE_PATTERN.match(value):
        raise ValueError(
            f"{field_name} must contain only letters, numbers, "
            f"underscores, and hyphens. Got: {value!r}"
        )

    return value
