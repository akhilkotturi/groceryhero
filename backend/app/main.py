from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.redis import init_redis, close_redis
from app.db.session import init_db
from app.api.routes import auth, users, deals, stores, grocery, planner, admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    await init_redis()
    yield
    # Shutdown
    await close_redis()


app = FastAPI(
    title="GroceryHero API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(deals.router, prefix="/api/deals", tags=["deals"])
app.include_router(stores.router, prefix="/api/stores", tags=["stores"])
app.include_router(grocery.router, prefix="/api/grocery-list", tags=["grocery"])
app.include_router(planner.router, prefix="/api/planner", tags=["planner"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "GroceryHero API"}
