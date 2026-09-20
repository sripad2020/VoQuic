import struct
import time
from typing import NamedTuple, Optional

HEADER_FORMAT = "!B16s16s16sIQB"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 62 bytes

CODEC_OPUS = 0x01
CODEC_PCM = 0x02

class VoicePacket(NamedTuple):
    version: int
    call_id: str
    sender_id: str
    whisper_target_id: str
    sequence: int
    timestamp: int
    codec: int
    payload: bytes

    def serialize(self) -> bytes:
        # Pack fields according to HEADER_FORMAT
        call_id_bytes = self.call_id.encode('ascii')[:16].ljust(16, b'\x00')
        sender_id_bytes = self.sender_id.encode('ascii')[:16].ljust(16, b'\x00')
        whisper_target_bytes = self.whisper_target_id.encode('ascii')[:16].ljust(16, b'\x00')
        
        header = struct.pack(
            HEADER_FORMAT,
            self.version,
            call_id_bytes,
            sender_id_bytes,
            whisper_target_bytes,
            self.sequence,
            self.timestamp,
            self.codec
        )
        return header + self.payload

    @classmethod
    def parse(cls, data: bytes) -> Optional["VoicePacket"]:
        if len(data) < HEADER_SIZE:
            return None
        
        try:
            version, call_id_bytes, sender_id_bytes, whisper_target_bytes, sequence, timestamp, codec = struct.unpack(
                HEADER_FORMAT, data[:HEADER_SIZE]
            )
            
            call_id = call_id_bytes.rstrip(b'\x00').decode('ascii', errors='ignore')
            sender_id = sender_id_bytes.rstrip(b'\x00').decode('ascii', errors='ignore')
            whisper_target_id = whisper_target_bytes.rstrip(b'\x00').decode('ascii', errors='ignore')
            payload = data[HEADER_SIZE:]
            
            return cls(
                version=version,
                call_id=call_id,
                sender_id=sender_id,
                whisper_target_id=whisper_target_id,
                sequence=sequence,
                timestamp=timestamp,
                codec=codec,
                payload=payload
            )
        except Exception:
            return None

def create_voice_packet(
    call_id: str,
    sender_id: str,
    sequence: int,
    payload: bytes,
    whisper_target_id: str = "",
    codec: int = CODEC_OPUS,
    timestamp: Optional[int] = None
) -> VoicePacket:
    if timestamp is None:
        timestamp = int(time.time() * 1000)
    return VoicePacket(
        version=1,
        call_id=call_id,
        sender_id=sender_id,
        whisper_target_id=whisper_target_id,
        sequence=sequence,
        timestamp=timestamp,
        codec=codec,
        payload=payload
    )
