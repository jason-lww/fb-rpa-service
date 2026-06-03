import uvicorn
from fastapi import FastAPI

from app.api import fb_account_flow_api
from app.core.config import settings
from app.core.logger import setup_logger


setup_logger()

app = FastAPI(title=settings.project_name)
app.include_router(fb_account_flow_api.router)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
