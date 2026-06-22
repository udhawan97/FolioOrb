from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.routers import stocks, portfolio, ai
from app.database import engine
from app import models


# lifespan runs once when the server starts up.
# We use it to create all database tables before the app begins accepting requests.
@asynccontextmanager
async def lifespan(_app: FastAPI):
    models.Base.metadata.create_all(bind=engine)
    yield  # The app runs while we're "inside" this yield

# Create the FastAPI application instance
app = FastAPI(
    title="FolioSenseAI",
    description=(
        "FolioSenseAI helps explain portfolio movement by surfacing "
        "market context, news, and AI-generated insights for holdings."
    ),
    version="0.4.1",
    lifespan=lifespan,
)

# Allow requests from any origin — required so browsers can call our API
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# Serve static files (CSS, JS, images) from the /static folder
# Files at static/css/style.css → URL: /static/css/style.css
app.mount("/static", StaticFiles(directory="static"), name="static")

# Register the route groups defined in our router files
app.include_router(stocks.router)
app.include_router(portfolio.router)
app.include_router(ai.router)



@app.get("/")
async def dashboard():
    """Serve the main dashboard HTML page."""
    return FileResponse("templates/index.html")

@app.get("/health")
async def health_check():
    """Simple endpoint to confirm the server is running."""
    return {"status": "healthy"}
