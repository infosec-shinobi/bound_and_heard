import secrets

from fastapi import HTTPException, Request, status


ADMIN_SESSION_KEY = "is_admin"


def is_admin_authenticated(request: Request) -> bool:
    return bool(request.session.get(ADMIN_SESSION_KEY))


def verify_admin_password(candidate: str, expected: str | None) -> bool:
    if not expected or not expected.strip():
        return False
    return secrets.compare_digest(candidate, expected)


def require_write_access(request: Request) -> None:
    if not request.app.state.writes_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write actions are disabled because BOUND_AND_HEARD_ADMIN_PASSWORD is not set.",
        )
    if not is_admin_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin login is required for write actions.",
        )
