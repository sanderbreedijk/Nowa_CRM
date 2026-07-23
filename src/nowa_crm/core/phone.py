from __future__ import annotations


def normalize_phone(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits.startswith("0031"):
        digits = "0" + digits[4:]
    elif digits.startswith("31") and len(digits) >= 11:
        digits = "0" + digits[2:]
    return digits


def format_phone(value: str) -> str:
    digits = normalize_phone(value)
    if not digits:
        return ""
    if len(digits) == 10 and digits.startswith("06"):
        return f"{digits[:2]}-{digits[2:]}"
    if len(digits) == 10 and digits.startswith("0"):
        return f"{digits[:3]}-{digits[3:]}"
    if value.strip().startswith("+") and not digits.startswith("0"):
        return "+" + digits
    return digits

