from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Bound & Heard")

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
