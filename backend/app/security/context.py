"""Per-request identity, carried with contextvars so that the layers below the
API (Supabase repositories, audit, observability) act *as the signed-in user*
without threading a token through every function signature.

Each HTTP request runs in its own asyncio task with its own copy of the
context, so values set here never leak between requests; tasks spawned while
handling a request (SSE streaming, LangGraph nodes) inherit them.
"""
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CurrentUser:
    auth_id: str  # Supabase Auth user id (auth.users.id)
    member_id: str  # in_users.id -- this app's membership row
    email: str | None
    role: str  # "admin" | "operator"
    display_name: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@dataclass(frozen=True)
class RequestMeta:
    request_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    extra: dict = field(default_factory=dict)


_access_token: ContextVar[str | None] = ContextVar("supabase_access_token", default=None)
_current_user: ContextVar[CurrentUser | None] = ContextVar("current_user", default=None)
_EMPTY_META = RequestMeta()
_request_meta: ContextVar[RequestMeta] = ContextVar("request_meta", default=_EMPTY_META)  # noqa: B039 - frozen


def set_access_token(token: str | None) -> None:
    _access_token.set(token)


def get_access_token() -> str | None:
    return _access_token.get()


def set_current_user(user: CurrentUser | None) -> None:
    _current_user.set(user)


def get_current_user() -> CurrentUser | None:
    return _current_user.get()


def set_request_meta(meta: RequestMeta) -> None:
    _request_meta.set(meta)


def get_request_meta() -> RequestMeta:
    return _request_meta.get()
