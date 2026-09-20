import logging
from typing import Optional
from app.audio.packet import VoicePacket
from app.quic.session import session_registry, VoiceSession

logger = logging.getLogger("pulse_relay.quic.relay")

class VoiceRelay:
    def __init__(self):
        self.total_relayed_packets: int = 0
        self.total_relayed_bytes: int = 0

    def process_datagram(self, raw_data: bytes, sender_session: Optional[VoiceSession] = None) -> bool:
        """
        Parses incoming raw QUIC DATAGRAM, inspects metadata, and forwards to target peer.
        Does NOT decode Opus audio payload.
        """
        packet = VoicePacket.parse(raw_data)
        if not packet:
            logger.warning("Received invalid or corrupt QUIC DATAGRAM packet")
            return False

        sender_id = packet.sender_id
        call_id = packet.call_id

        # Update sender stats
        if sender_session:
            sender_session.record_rx(len(raw_data))

        # Look up destination client for this call
        dest_id = session_registry.get_destination(sender_id, call_id)
        if not dest_id:
            logger.debug(f"No active destination for call {call_id} from sender {sender_id}")
            return False

        dest_session = session_registry.get_session(dest_id)
        if not dest_session or not dest_session.protocol:
            logger.warning(f"Destination session for client {dest_id} is disconnected or invalid")
            return False

        # Relay raw datagram frame to destination peer
        try:
            dest_session.protocol.send_datagram(raw_data)
            dest_session.record_tx(len(raw_data))
            self.total_relayed_packets += 1
            self.total_relayed_bytes += len(raw_data)
            return True
        except Exception as e:
            logger.error(f"Failed to relay datagram from {sender_id} to {dest_id}: {e}")
            return False

voice_relay = VoiceRelay()
