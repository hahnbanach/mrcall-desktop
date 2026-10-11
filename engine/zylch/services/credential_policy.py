"""Finance configuration is private to its dedicated engine connection flow."""


def excluded_finance_setting(key) -> bool:
    return isinstance(key, str) and key.strip().upper().startswith("QONTO_")
