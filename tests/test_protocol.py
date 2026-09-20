import unittest
import time
from app.audio.packet import VoicePacket, create_voice_packet, HEADER_SIZE, CODEC_OPUS
from app.audio.jitter import JitterBuffer
from app.audio.codec import OpusCodec
from app.models.messages import SignalMessage, MessageType, CallState

class TestPulseRelayProtocol(unittest.TestCase):

    def test_voice_packet_serialization(self):
        call_id = "call_test123"
        sender_id = "CLIENT-A"
        seq = 1050
        payload = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        
        pkt = create_voice_packet(
            call_id=call_id,
            sender_id=sender_id,
            sequence=seq,
            payload=payload,
            whisper_target_id="CLIENT-B",
            codec=CODEC_OPUS
        )
        
        raw_bytes = pkt.serialize()
        self.assertGreaterEqual(len(raw_bytes), HEADER_SIZE + len(payload))
        
        parsed = VoicePacket.parse(raw_bytes)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.version, 1)
        self.assertEqual(parsed.call_id, call_id)
        self.assertEqual(parsed.sender_id, sender_id)
        self.assertEqual(parsed.whisper_target_id, "CLIENT-B")
        self.assertEqual(parsed.sequence, seq)
        self.assertEqual(parsed.codec, CODEC_OPUS)
        self.assertEqual(parsed.payload, payload)

    def test_jitter_buffer_sequence_and_loss(self):
        jb = JitterBuffer(min_buffer_ms=20, target_buffer_ms=40, max_buffer_ms=100)
        
        p100 = create_voice_packet("call1", "CLIENT-A", 100, b"frame100")
        p101 = create_voice_packet("call1", "CLIENT-A", 101, b"frame101")
        # Gap: 102 missing
        p103 = create_voice_packet("call1", "CLIENT-A", 103, b"frame103")

        jb.push(p100)
        jb.push(p101)
        jb.push(p103)

        telemetry = jb.get_telemetry()
        self.assertEqual(telemetry["packets_rx"], 3)
        self.assertEqual(telemetry["packets_lost"], 1)

    def test_signaling_messages(self):
        msg = SignalMessage(
            type=MessageType.QUIC_INFO,
            call_id="call_999",
            quic_host="192.168.1.10",
            quic_port=4433,
            cert_hash="a1b2c3d4e5f6"
        )
        json_str = msg.model_dump_json()
        self.assertIn("QUIC_INFO", json_str)
        self.assertIn("4433", json_str)

    def test_room_signaling(self):
        msg = SignalMessage(
            type=MessageType.CREATE_ROOM,
            room_id="ROOM-101",
            client_id="CLIENT-A"
        )
        json_str = msg.model_dump_json()
        self.assertIn("CREATE_ROOM", json_str)
        self.assertIn("ROOM-101", json_str)

    def test_opus_codec_instantiation(self):
        codec = OpusCodec()
        pcm_frame = b"\x00" * (960 * 2)  # 20ms mono PCM
        encoded = codec.encode(pcm_frame)
        self.assertIsNotNone(encoded)
        decoded = codec.decode(encoded)
        self.assertIsNotNone(decoded)

if __name__ == "__main__":
    unittest.main()
