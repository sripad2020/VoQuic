import time
import logging
from typing import Dict, Optional, Tuple
from app.audio.packet import VoicePacket

logger = logging.getLogger("pulse_relay.jitter")

class JitterBuffer:
    def __init__(
        self,
        min_buffer_ms: int = 20,
        target_buffer_ms: int = 40,
        max_buffer_ms: int = 100,
        frame_duration_ms: int = 20
    ):
        self.min_buffer_ms = min_buffer_ms
        self.target_buffer_ms = target_buffer_ms
        self.max_buffer_ms = max_buffer_ms
        self.frame_duration_ms = frame_duration_ms

        self.buffer: Dict[int, VoicePacket] = {}
        self.expected_seq: Optional[int] = None
        
        # Telemetry state
        self.packets_rx: int = 0
        self.packets_lost: int = 0
        self.jitter_ms: float = 0.0
        self.last_arrival_ms: Optional[float] = None
        self.last_transit_ms: Optional[float] = None
        self.max_seq_received: int = -1

    def push(self, packet: VoicePacket):
        now_ms = time.time() * 1000.0
        self.packets_rx += 1
        seq = packet.sequence

        # Calculate RFC 3550 Jitter
        if self.last_arrival_ms is not None and self.last_transit_ms is not None:
            transit_ms = now_ms - packet.timestamp
            d = abs(transit_ms - self.last_transit_ms)
            self.jitter_ms += (d - self.jitter_ms) / 16.0
        
        self.last_arrival_ms = now_ms
        self.last_transit_ms = now_ms - packet.timestamp

        # Detect sequence gaps and track loss
        if self.max_seq_received != -1:
            if seq > self.max_seq_received + 1:
                gap = seq - (self.max_seq_received + 1)
                self.packets_lost += gap
                logger.warning(f"Sequence gap detected: missing {gap} packet(s) between {self.max_seq_received} and {seq}")
        self.max_seq_received = max(self.max_seq_received, seq)

        if self.expected_seq is None:
            self.expected_seq = seq

        # Store in buffer if not too old
        if seq >= self.expected_seq:
            self.buffer[seq] = packet
            
        # Enforce max buffer size by dropping oldest if buffer exceeds max_buffer_ms
        max_frames = self.max_buffer_ms // self.frame_duration_ms
        if len(self.buffer) > max_frames:
            min_seq = min(self.buffer.keys())
            del self.buffer[min_seq]
            if min_seq == self.expected_seq:
                self.expected_seq += 1

    def pop((self)) -> Tuple[Optional[VoicePacket], bool]:
        """
        Pops the next packet in order.
        Returns (packet, is_plc) tuple.
        If a packet was lost, returns (None, True) to indicate Packet Loss Concealment (PLC).
        """
        if self.expected_seq is None or not self.buffer:
            return None, False

        # Wait until target buffer is primed
        target_frames = self.target_buffer_ms // self.frame_duration_ms
        if len(self.buffer) < target_frames and (max(self.buffer.keys()) - self.expected_seq < target_frames):
            return None, False

        if self.expected_seq in self.buffer:
            packet = self.buffer.pop(self.expected_seq)
            self.expected_seq += 1
            return packet, False

        # Sequence gap: missing expected packet.
        # Skip expected_seq and trigger PLC
        logger.debug(f"Jitter buffer triggering PLC for missing sequence {self.expected_seq}")
        self.expected_seq += 1
        return None, True

    def get_telemetry(self) -> dict:
        total = self.packets_rx + self.packets_lost
        loss_pct = (self.packets_lost / total * 100.0) if total > 0 else 0.0
        depth_ms = len(self.buffer) * self.frame_duration_ms

        return {
            "jitter_ms": round(self.jitter_ms, 2),
            "packet_loss_pct": round(loss_pct, 2),
            "packets_rx": self.packets_rx,
            "packets_lost": self.packets_lost,
            "buffer_depth_ms": depth_ms
        }
