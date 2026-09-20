import enum
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field, ConfigDict

class MessageType(str, enum.Enum):
    REGISTER = "REGISTER"
    CLIENT_LIST = "CLIENT_LIST"
    CREATE_ROOM = "CREATE_ROOM"
    JOIN_ROOM = "JOIN_ROOM"
    LEAVE_ROOM = "LEAVE_ROOM"
    ROOM_UPDATE = "ROOM_UPDATE"
    CALL = "CALL"
    CALL_INCOMING = "CALL_INCOMING"
    CALL_ACCEPT = "CALL_ACCEPT"
    CALL_REJECT = "CALL_REJECT"
    QUIC_INFO = "QUIC_INFO"
    CALL_CONNECTED = "CALL_CONNECTED"
    CALL_END = "CALL_END"
    MUTE = "MUTE"
    CHAT_MESSAGE = "CHAT_MESSAGE"
    EMOJI_REACTION = "EMOJI_REACTION"
    CONGESTION_TELEMETRY = "CONGESTION_TELEMETRY"
    PING = "PING"
    PONG = "PONG"
    ERROR = "ERROR"

class CallState(str, enum.Enum):
    IDLE = "IDLE"
    IN_ROOM = "IN_ROOM"
    CALLING = "CALLING"
    RINGING = "RINGING"
    ACCEPTED = "ACCEPTED"
    QUIC_CONNECTING = "QUIC_CONNECTING"
    CONNECTED = "CONNECTED"
    VOICE_ACTIVE = "VOICE_ACTIVE"
    ENDING = "ENDING"
    ENDED = "ENDED"

class RoomInfo(BaseModel):
    model_config = ConfigDict(extra='ignore')
    id: str
    member_count: int
    members: List[str]

class ClientInfo(BaseModel):
    model_config = ConfigDict(extra='ignore')
    id: str
    status: CallState = CallState.IDLE
    room_id: Optional[str] = None
    call_id: Optional[str] = None

class SignalMessage(BaseModel):
    model_config = ConfigDict(extra='ignore')
    type: MessageType
    client_id: Optional[str] = None
    target_id: Optional[str] = None
    room_id: Optional[str] = None
    call_id: Optional[str] = None
    reason: Optional[str] = None
    muted: Optional[bool] = None
    text: Optional[str] = None
    emoji: Optional[str] = None
    quic_host: Optional[str] = None
    quic_port: Optional[int] = None
    cert_hash: Optional[str] = None
    whisper_target_id: Optional[str] = None
    clients: Optional[List[ClientInfo]] = None
    members: Optional[List[ClientInfo]] = None
    rooms: Optional[List[RoomInfo]] = None
    payload: Optional[Dict[str, Any]] = None
