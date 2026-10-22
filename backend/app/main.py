"""应用入口。在backend目录运行 python -m uvicorn app.main:app --reload。"""
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request

from app.auth.api import router as auth_router
from app.database import create_lifespan
from app.responses.api import router as responses_router
from app.stats.api import router as statistics_router
from app.surveys.api import router as surveys_router

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def create_app(test_database=None, test_secret: str | None = None) -> FastAPI:
    application = FastAPI(title="问卷系统 API", lifespan=create_lifespan(test_database, test_secret))
    application.include_router(responses_router)
    application.include_router(statistics_router)

    @application.get("/api/health")
    def health(request: Request):
        request.app.state.db.command("ping")
        return {"status": "ok"}

    application.include_router(auth_router)
    application.include_router(surveys_router)
    return application


app = create_app()
