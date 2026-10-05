"""
Broadcast & NDI Video Output REST Endpoints for VerbaClear.
Provides broadcast monitoring, NDI streaming controls, and transparent HTTP video streams.
"""

import asyncio
import logging
from typing import Optional
from fastapi import APIRouter, Body, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(tags=["Broadcast & NDI"])
logger = logging.getLogger(__name__)


class ToggleNDIRequest(BaseModel):
    enabled: Optional[bool] = Field(None, description="True to enable, False to disable, None to toggle")


@router.get("/api/broadcast/status")
async def get_broadcast_status():
    """Returns status and telemetry for the NDI broadcast output and transparent video stream."""
    from src.api.main import orchestrator
    if not orchestrator or not hasattr(orchestrator, "ndi_adapter"):
        raise HTTPException(status_code=503, detail="Broadcast subsystem not initialized")
    return orchestrator.ndi_adapter.get_status()


@router.post("/api/control/ndi/toggle")
async def toggle_ndi_streaming(request: Optional[ToggleNDIRequest] = Body(None)):
    """Toggles or sets the NDI / alpha video broadcast stream on or off."""
    from src.api.main import orchestrator
    if not orchestrator or not hasattr(orchestrator, "ndi_adapter"):
        raise HTTPException(status_code=503, detail="Broadcast subsystem not initialized")

    force_state = request.enabled if request else None
    is_streaming = orchestrator.ndi_adapter.toggle_streaming(force_state=force_state)
    status = orchestrator.ndi_adapter.get_status()

    return {
        "status": "success",
        "action": "NDI_STREAM_TOGGLED",
        "isStreaming": is_streaming,
        "mode": status["mode"],
        "streamName": status["streamName"],
        "message": f"Broadcast stream {'ACTIVATED' if is_streaming else 'PAUSED'}.",
    }


@router.get("/api/broadcast/frame")
async def get_broadcast_frame():
    """
    Returns the latest rendered 1920x1080 frame with full alpha transparency as a PNG image.
    Suitable for video mixer still-image capture or polling.
    """
    from src.api.main import orchestrator
    if not orchestrator or not hasattr(orchestrator, "ndi_adapter"):
        raise HTTPException(status_code=503, detail="Broadcast subsystem not initialized")

    png_bytes = orchestrator.ndi_adapter.get_current_frame_png()
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/api/broadcast/stream/alpha")
async def get_transparent_alpha_stream(
    fps: int = Query(15, ge=1, le=30, description="Target frame rate for the HTTP multipart stream"),
):
    """
    Live multipart PNG video stream with true alpha channel transparency.
    Can be ingested directly by OBS Browser / Media Source, VLC, or vMix.
    """
    from src.api.main import orchestrator
    if not orchestrator or not hasattr(orchestrator, "ndi_adapter"):
        raise HTTPException(status_code=503, detail="Broadcast subsystem not initialized")

    frame_interval = 1.0 / max(1, fps)

    async def frame_generator():
        try:
            while True:
                t0 = asyncio.get_event_loop().time()
                png_bytes = orchestrator.ndi_adapter.get_current_frame_png()

                header = (
                    b"--frame\r\n"
                    b"Content-Type: image/png\r\n"
                    b"Content-Length: " + str(len(png_bytes)).encode("ascii") + b"\r\n\r\n"
                )
                yield header + png_bytes + b"\r\n"

                elapsed = asyncio.get_event_loop().time() - t0
                sleep_delay = max(0.005, frame_interval - elapsed)
                await asyncio.sleep(sleep_delay)
        except (asyncio.CancelledError, GeneratorExit):
            pass

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        },
    )
