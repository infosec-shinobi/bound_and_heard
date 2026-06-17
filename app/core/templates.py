from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.core.write_protection import is_admin_authenticated


templates = Jinja2Templates(directory="app/templates")


def template_context(request: Request, **values: object) -> dict[str, object]:
    writes_enabled = bool(request.app.state.writes_enabled)
    is_admin = is_admin_authenticated(request)
    can_write = writes_enabled and is_admin

    if can_write:
        disabled_reason = None
    elif writes_enabled:
        disabled_reason = "Admin login is required for write actions."
    else:
        disabled_reason = "Set BOUND_AND_HEARD_ADMIN_PASSWORD to enable write actions."

    context: dict[str, object] = {
        "request": request,
        "app_name": request.app.state.settings.app_name,
        "writes_enabled": writes_enabled,
        "is_admin": is_admin,
        "can_write": can_write,
        "write_disabled_reason": disabled_reason,
    }
    context.update(values)
    return context
