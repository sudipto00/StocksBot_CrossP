"""
StocksBot FastAPI Backend
Main application entry point for the sidecar backend.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(
    title="StocksBot API",
    description="Cross-platform StocksBot backend service",
    version="0.1.0"
)

# Configure CORS for Tauri frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420", "tauri://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "StocksBot API"}


@app.get("/status")
async def status():
    """
    Health check endpoint.
    Returns the status of the backend service.
    """
    return {
        "status": "running",
        "service": "StocksBot Backend",
        "version": "0.1.0"
    }


# TODO: Import and register API routes from api/ module
# from api import routes
# app.include_router(routes.router)


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )
