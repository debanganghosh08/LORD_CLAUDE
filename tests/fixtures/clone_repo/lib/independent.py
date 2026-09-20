"""A different validator that happens to look similar: a user profile, not an order."""
import re

EMAIL = re.compile(r"^[^@]+@[^@]+$")
ROLES = ("admin", "editor", "viewer")


def validate_profile(profile: dict) -> list[str]:
    errors: list[str] = []
    email = str(profile.get("email") or "").strip().lower()
    if not EMAIL.match(email):
        errors.append("email is not valid")
    if profile.get("role") not in ROLES:
        errors.append(f"role must be one of {', '.join(ROLES)}")
    age = profile.get("age")
    if age is not None and (not isinstance(age, int) or age < 13):
        errors.append("age must be 13 or more")
    name = str(profile.get("display_name") or "").strip()
    if len(name) > 40:
        errors.append("display_name longer than 40 characters")
    if profile.get("newsletter") not in (True, False, None):
        errors.append("newsletter must be a boolean")
    return errors
