"""AI Knowledge Compiler control-plane API."""

from fastapi import FastAPI

from akc_api.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API lazily so parser subprocesses do not import route adapters."""

    from akc_api.main import create_app as create_application

    return create_application(settings)

__all__ = ["create_app"]
