import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import auth
from app.agents.graph import get_compiled_graph
from app.api import conversations, health, reference_data, reports, source_settings
from app.config.settings import get_settings
from app.ingestion.source_settings_store import effective_source_config
from app.providers.factory import get_data_provider
from app.services.conversation_service import ConversationService

logger = logging.getLogger(__name__)


def _check_production_security(settings) -> None:
    """Loud, non-fatal warnings when running with insecure defaults in
    "production" (SECURITY_REVIEW.md production checklist) -- deliberately
    doesn't refuse to start: this project has one operator, not a fleet of
    unattended deployments, so a hard crash would just as likely lock out a
    legitimate admin mid-incident as stop a real misconfiguration. Loud logs
    are the right tradeoff here."""
    if settings.environment != "production":
        return
    if settings.auth_secret_key == "dev-insecure-change-me":
        logger.critical(
            "SECURITY: running with environment=production but AUTH_SECRET_KEY is still the "
            "insecure default -- JWTs are forgeable by anyone who knows this. Set a real random "
            "secret in backend/.env."
        )
    if settings.auth_password == "123456":
        logger.critical(
            "SECURITY: running with environment=production but AUTH_PASSWORD is still the "
            "default '123456'. Change AUTH_USERNAME/AUTH_PASSWORD in backend/.env."
        )
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
    config = effective_source_config(settings)
    problems = config.problems()
    if problems:
        logger.error("Fuente de datos HTTP sin configurar en backend/.env: %s", "; ".join(problems))
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(conversations.router)
    app.include_router(reports.router)
    app.include_router(reference_data.router)
    app.include_router(source_settings.router)

    return app


app = create_app()
