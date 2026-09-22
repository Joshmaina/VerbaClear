"""
FastAPI Real-Time Gateway & ASGI Entrypoint for VerbaClear.
Manages the application lifecycle, WebSocket routes, and REST endpoints.
"""

from contextlib import asynccontextmanager
import logging
import sys
import uvicorn
from pathlib import Path
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from src.api.routers.export import router as export_router
from src.api.routers.session import router as session_router
from src.api.ws.hub import WebSocketHub
from src.application.orchestrator import VerbaClearOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("verbaclear")

# Paths to self-contained web interfaces
WEB_DIR = Path(__file__).parent.parent / "web"
STAGE_HTML = WEB_DIR / "stage" / "index.html"
COMPANION_HTML = WEB_DIR / "companion" / "index.html"

# Global instances
ws_hub = WebSocketHub()
orchestrator = VerbaClearOrchestrator(ws_hub=ws_hub)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages application startup and graceful shutdown."""
    import asyncio
    logger.info("Initializing VerbaClear ASGI runtime...")
    loop = asyncio.get_running_loop()
    orchestrator.attach_event_loop(loop)

    # Note: Orchestrator audio stream can be started here or triggered via API
    logger.info("VerbaClear WebSocket hub and orchestrator ready.")
    yield
    logger.info("Shutting down VerbaClear ASGI runtime...")
    await orchestrator.stop()


app = FastAPI(
    title="VerbaClear API",
    description="Real-Time Speech Intelligence and Vocabulary Simplification Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# Enable CORS for local stage overlays and mobile companions
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session_router)
app.include_router(export_router)


@app.get("/stage")
async def get_stage_display():
    """Serves the standalone lower-third stage overlay for OBS / video switchers."""
    if not STAGE_HTML.exists():
        raise HTTPException(status_code=404, detail="Stage display template not found")
    return FileResponse(STAGE_HTML, media_type="text/html")


@app.get("/companion")
async def get_companion_portal():
    """Serves the attendee mobile companion portal for smartphones & tablets."""
    if not COMPANION_HTML.exists():
        raise HTTPException(status_code=404, detail="Companion template not found")
    return FileResponse(COMPANION_HTML, media_type="text/html")


@app.get("/api/health")
async def health_check():
    """Health check endpoint for AV appliance monitoring."""
    return {
        "status": "healthy",
        "service": "VerbaClear",
        "version": "0.1.0",
        "activeClients": {
            "stage": ws_hub.stage_client_count,
            "audience": ws_hub.audience_client_count,
        },
    }


@app.websocket("/ws/stage")
async def websocket_stage_endpoint(websocket: WebSocket):
    """WebSocket channel for the Primary Stage Lower-Third Overlay."""
    await ws_hub.connect_stage(websocket)
    try:
        while True:
            # Stage overlay is passive; listen for heartbeats / client pings
            _ = await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        await ws_hub.disconnect_stage(websocket)


@app.websocket("/ws/audience")
async def websocket_audience_endpoint(websocket: WebSocket):
    """WebSocket channel for the Audience Mobile Companion PWA."""
    await ws_hub.connect_audience(websocket)
    try:
        while True:
            # Listen for attendee heartbeat or ping messages
            _ = await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        await ws_hub.disconnect_audience(websocket)


@app.websocket("/ws/telemetry")
async def websocket_telemetry_endpoint(websocket: WebSocket):
    """WebSocket channel for AV production consoles and appliance metrics."""
    await ws_hub.connect_telemetry(websocket)
    try:
        while True:
            _ = await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        await ws_hub.disconnect_telemetry(websocket)


def cli_entrypoint():
    """CLI launcher invoked via 'verbaclear' command."""
    import argparse
    parser = argparse.ArgumentParser(description="VerbaClear Real-Time Speech Appliance")
    parser.add_argument("--host", default="0.0.0.0", help="Binding host IP")
    parser.add_argument("--port", type=int, default=8000, help="HTTP/WS port")
    parser.add_argument("--start-audio", action="store_true", help="Auto-start live mic capture")
    args = parser.parse_args()

    if args.start_audio:
        orchestrator.start()

    uvicorn.run("src.api.main:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    cli_entrypoint()
