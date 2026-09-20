import time
import logging
from typing import Dict, Optional, Tuple, Any

logger = logging.getLogger("pulse_relay.quic.session")

class VoiceSession:
    def __init__(self, client_id: str, protocol: Any):
        self.client_id = client_id
        self.protocol = protocol
        self.call_id: Optional[str] = None
        self.peer_id: Optional[str] = None
        
        # Telemetry counters
        self.packets_tx: int = 0
        self.packets_rx: int = 0
        self.bytes_tx: int = 0
        self.bytes_rx: int = 0
        self.rtt_ms: float = 0.0
        self.created_at: float = time.time()
        self.last_active: float = time.time()

    def record_rx(self, num_bytes: int):
        self.packets_rx += 1
        self.bytes_rx += num_bytes
        self.last_active = time.time()

    def record_tx(self, num_bytes: int):
        self.packets_tx += 1
        self.bytes_tx += num_bytes
        self.last_active = time.time()

    def get_telemetry(self) -> dict:
        return {
            "client_id": self.client_id,
            "peer_id": self.peer_id,
            "call_id": self.call_id,
            "packets_tx": self.packets_tx,
            "packets_rx": self.packets_rx,
            "bytes_tx": self.bytes_tx,
            "bytes_rx": self.bytes_rx,
            "rtt_ms": round(self.rtt_ms, 2),
            "active_seconds": round(time.time() - self.created_at, 1)
        }

class SessionRegistry:
    def __init__(self):
        # client_id -> VoiceSession
        self.sessions: Dict[str, VoiceSession] = {}
        # call_id -> (caller_id, target_id)
        self.calls: Dict[str, Tuple[str, str]] = {}

    def register_session(self, client_id: str, protocol: Any) -> VoiceSession:
        session = VoiceSession(client_id, protocol)
        self.sessions[client_id] = session
        logger.info(f"Registered QUIC session for client {client_id}")
        return session

    def unregister_session(self, client_id: str):
        if client_id in self.sessions:
            del self.sessions[client_id]
            logger.info(f"Unregistered QUIC session for client {client_id}")

    def bind_call(self, call_id: str, caller_id: str, target_id: str):
        self.calls[call_id] = (caller_id, target_id)
        if caller_id in self.sessions:
            self.sessions[caller_id].call_id = call_id
            self.sessions[caller_id].peer_id = target_id
        if target_id in self.sessions:
            self.sessions[target_id].call_id = call_id
            self.sessions[target_id].peer_id = caller_id
        logger.info(f"Bound call {call_id} between QUIC clients {caller_id} <-> {target_id}")

    def unbind_call(self, call_id: str):
        if call_id in self.calls:
            caller_id, target_id = self.calls.pop(call_id)
            for c_id in (caller_id, target_id):
                if c_id in self.sessions:
                    self.sessions[c_id].call_id = None
                    self.sessions[c_id].peer_id = None

    def get_destination(self, sender_id: str, call_id: str) -> Optional[str]:
        if call_id in self.calls:
            caller_id, target_id = self.calls[call_id]
            if sender_id == caller_id:
                return target_id
            elif sender_id == target_id:
                return caller_id
        return None

    def get_session(self, client_id: str) -> Optional[VoiceSession]:
        return self.sessions.get(client_id)

session_registry = SessionRegistry()
