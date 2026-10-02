import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.graph import get_compiled_graph
from app.api import (
    audit_log,
    conversations,
    health,
    llm,
    llm_evaluations,
    me,
    observability,
    reference_data,
    reports,
    source_settings,
)
from app.config.settings import get_settings
from app.providers.factory import get_data_provider
from app.security.middleware import RequestContextMiddleware
from app.services import source_settings_service
from app.services.conversation_service import ConversationService

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """INFO for the app's own loggers (app.audit / app.ops lines included), with level names
    the operators can grep for. uvicorn keeps configuring its own loggers."""
    app_logger = logging.getLogger("app")
    if app_logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)
    # propagates to the root logger too (no handler there by default, so no duplicates)


_configure_logging()


def _check_production_security(settings) -> None:
    """Loud, non-fatal warnings when running with an insecure or incomplete setup
    (SECURITY_REVIEW.md checklist). Deliberately doesn't refuse to start: an admin
    must still be able to sign in and fix what can be fixed from the app."""
    if not settings.supabase_url or not settings.supabase_anon_key:
        logger.critical(
            "SECURITY: SUPABASE_URL / SUPABASE_ANON_KEY no están configuradas -- nadie podrá iniciar sesión."
        )
    if not settings.source_secret_key.get_secret_value().strip():
        logger.warning(
            "SOURCE_SECRET_KEY no está configurada: la contraseña de la fuente no se podrá guardar cifrada "
            "desde Fuente de Datos."
        )
    if settings.environment != "production":
        return
    if any("localhost" in origin for origin in settings.cors_origins):
        logger.warning(
            "SECURITY: running with environment=production but CORS_ORIGINS still includes a "
            "localhost entry (%s) -- update it to the real frontend origin.",
            settings.cors_origins,
        )


def _check_data_source(settings) -> None:
    """Report an unusable alarm-source configuration at startup, loudly but without
    refusing to start (the operator can still log in and fix it; every report
    attempt also fails with the same explicit message)."""
    if settings.data_provider != "http":
        return
    # Startup has no signed-in user, so only the backend/.env bootstrap values are visible here;
    # what was saved from Fuente de Datos is applied on the first request.
    config = source_settings_service.to_source_config(source_settings_service.settings_from_env(settings), settings)
    problems = config.problems()
    if problems:
        logger.info(
            "Fuente de datos: backend/.env no trae valores iniciales completos (%s); se usará lo configurado "
            "en Fuente de Datos.",
            "; ".join(problems),
        )
        return
    logger.info(
        "Fuente de datos: %s (usuario configurado, TLS %s)",
        config.host,
        "verificado" if config.tls_verify else "SIN verificar",
    )
    if not config.uses_https:
        logger.warning(
            "SECURITY: SOURCE_BASE_URL usa http:// -- las credenciales de la fuente viajan sin cifrar por la red. "
            "Usar https:// si el servidor lo permite."
        )
    if settings.environment == "production":
        if not config.tls_verify:
            logger.warning("SECURITY: SOURCE_VERIFY_TLS=false en producción -- la identidad del servidor no se verifica.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _check_production_security(settings)
    _check_data_source(settings)

    graph, saver_ctx = await get_compiled_graph(str(settings.sqlite_checkpoint_db_path))
    app.state.conversation_service = ConversationService(graph)

    try:
        yield
    finally:
        await saver_ctx.__aexit__(None, None, None)
        if get_data_provider.cache_info().currsize:
            provider = get_data_provider()
            if hasattr(provider, "aclose"):
                await provider.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AI Security Report Generator", lifespan=lifespan)

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(conversations.router)
    app.include_router(reports.router)
    app.include_router(reference_data.router)
    app.include_router(source_settings.router)
    app.include_router(audit_log.router)
    app.include_router(observability.router)
    app.include_router(llm_evaluations.router)  # before llm.router: /evaluations is more specific
    app.include_router(llm.router)

    return app


app = create_app()
