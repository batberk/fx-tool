from fastapi import FastAPI

from app.config import Settings
from app.errors import register_error_handlers


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="fx-tool")
    register_error_handlers(app)

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    return app


app = create_app()
