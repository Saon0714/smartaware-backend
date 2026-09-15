"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.api.router import api_router
from app.core.config import settings
from app.db import schema_version


def custom_generate_unique_id(route: APIRoute) -> str:
    """Produce stable, readable operation IDs.

    FastAPI's default IDs include the path and method, which makes generated
    TypeScript client functions unreadable (`health_api_v1_health_get`). Tagging
    them `tag_name` yields `healthHealth` -> clean names in the frontend client.
    Changing this later churns every generated symbol, so it is set from day one.
    """
    # The LAST tag, not the first: when a router is nested inside another,
    # FastAPI prepends the parent's tags, so tags[0] would be the shared parent
    # ("admin-content") for every child and every operation ID would collide.
    # The last entry is always the most specific router's own tag.
    tag = route.tags[-1] if route.tags else "default"
    return f"{tag}_{route.name}"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Say so at startup if the database is behind on migrations.

    A pull that brings new columns leaves an existing database one migration
    short, and the only symptom is a 500 on every page that reads the changed
    table. Logging it here turns that into a sentence naming the command to
    run.
    """
    schema_version.warn_if_stale()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        lifespan=lifespan,
        title=settings.PROJECT_NAME,
        version="0.1.0",
        openapi_url="/openapi.json",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
        generate_unique_id_function=custom_generate_unique_id,
    )

    # The frontend is a separate origin, so CORS is a real security boundary
    # rather than a formality. Origins come from the environment and are always
    # an explicit allowlist — `allow_credentials` with a wildcard is rejected by
    # browsers and would be unsafe regardless.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    return app


app = create_app()
