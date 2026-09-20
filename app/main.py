import os
import socket
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.signaling.websocket import manager
from app.quic.server import quic_server
from app.quic.voice_relay import voice_relay

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pulse_relay.main")

def get_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not send actual data
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

HTTP_PORT = int(os.environ.get("HTTP_PORT", 8000))
QUIC_PORT = int(os.environ.get("QUIC_PORT", 4433))
HOST = os.environ.get("HOST", "0.0.0.0")

@asynccontextmanager
async def lifespan(app: FastAPI):
    lan_ip = get_lan_ip()
    logger.info("=" * 60)
    logger.info("           PULSE RELAY VOICE-OVER-QUIC SERVER")
    logger.info("=" * 60)
    logger.info(f" Web UI & Signaling : http://{lan_ip}:{HTTP_PORT}")
    logger.info(f" Local Access       : http://localhost:{HTTP_PORT}")
    logger.info(f" QUIC Voice Endpoint: UDP {lan_ip}:{QUIC_PORT}")
    logger.info("=" * 60)

    # Initialize QUIC server
    quic_server.port = QUIC_PORT
    quic_server.host = HOST
    await quic_server.start()

    # Pass LAN IP & QUIC info to WebSocket signaling manager
    manager.set_quic_info(
        host=lan_ip,
        port=QUIC_PORT,
        cert_hash=quic_server.cert_hash
    )

    yield

    logger.info("Shutting down Pulse Relay server...")
    await quic_server.stop()

app = FastAPI(title="Pulse Relay Voice-over-QUIC", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    return FileResponse(index_path)

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "active_clients": len(manager.clients),
        "active_calls": len(manager.active_calls),
        "quic_running": quic_server.is_running,
        "relayed_packets": voice_relay.total_relayed_packets,
        "relayed_bytes": voice_relay.total_relayed_bytes
    }

from fastapi import Request

@app.post("/api/register")
async def register_endpoint(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    req_id = data.get("client_id")
    client_id = manager.register_polling_client(req_id)
    signals = manager.pop_signals(client_id)
    return {"status": "ok", "client_id": client_id, "signals": signals}

@app.post("/api/signal")
async def signal_endpoint(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    client_id = data.get("client_id")
    signal_payload = data.get("signal")
    if client_id and signal_payload:
        import json
        await manager.handle_message(client_id, json.dumps(signal_payload))
    signals = manager.pop_signals(client_id) if client_id else []
    return {"status": "ok", "signals": signals}

@app.get("/api/poll")
async def poll_endpoint(client_id: str):
    signals = manager.pop_signals(client_id)
    return {"status": "ok", "signals": signals}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, client_id: str = None):
    connected_id = await manager.connect(websocket, requested_id=client_id)
    try:
        while True:
            message = await websocket.receive()
            if "text" in message and message["text"]:
                await manager.handle_message(connected_id, message["text"])
            elif "bytes" in message and message["bytes"]:
                await manager.handle_binary_media(connected_id, message["bytes"])
    except WebSocketDisconnect:
        await manager.disconnect(connected_id)
    except Exception as e:
        logger.error(f"WebSocket error for {connected_id}: {e}")
        await manager.disconnect(connected_id)
