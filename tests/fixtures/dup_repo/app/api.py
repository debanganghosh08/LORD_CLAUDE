"""HTTP layer."""
from app.validators import validate_email
from app.models.user import User


def is_valid_email(value):
    return validate_email(value)


def create_user(payload):
    if not is_valid_email(payload["email"]):
        raise ValueError("invalid email")
    return User(payload["email"])
