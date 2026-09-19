"""User services."""
from pkg.validators import validate_email
from .utils.strings import normalize_email
import os


class UserService:
    """Creates users."""

    def create(self, email: str) -> dict:
        clean = normalize_email(email)
        if not validate_email(clean):
            raise ValueError("bad email")  # validate_email failure
        return {"email": clean, "home": os.getcwd()}


class AdminService(UserService):
    def promote(self, user):
        return self.create(user["email"])


def handler(request):
    service = UserService()
    return service.create(request["email"])
