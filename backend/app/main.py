from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.agent import AGENT_DOMAIN_ERRORS, agent_error_handler
from app.api.agent import router as agent_router
from app.api.health import router as health_router
from app.api.dependencies import close_agent_runtime


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    close_agent_runtime()


app = FastAPI(title="AgentFlow AI", version="0.1.0", lifespan=lifespan)
app.include_router(health_router, prefix="/api")
app.include_router(agent_router, prefix="/api")

for exception_type in AGENT_DOMAIN_ERRORS:
    app.add_exception_handler(exception_type, agent_error_handler)
