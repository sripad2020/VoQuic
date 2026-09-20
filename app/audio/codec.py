import logging
from typing import Optional

logger = logging.getLogger("pulse_relay.codec")

SAMPLE_RATE = 48000
CHANNELS = 1
FRAME_DURATION_MS = 20
SAMPLES_PER_FRAME = int(SAMPLE_RATE * (FRAME_DURATION_MS / 1000.0))  # 960 samples

class OpusCodec:
    def __init__(self, sample_rate: int = SAMPLE_RATE, channels: int = CHANNELS):
        self.sample_rate = sample_rate
        self.channels = channels
        self.encoder = None
        self.decoder = None
        self.has_opus = False
        
        # Try initializing native opus library if installed
        try:
            import opuslib
            self.encoder = opuslib.Encoder(self.sample_rate, self.channels, opuslib.APPLICATION_VOIP)
            self.decoder = opuslib.Decoder(self.sample_rate, self.channels)
            self.has_opus = True
            logger.info("Native Opus codec initialized via opuslib")
        except ImportError:
            try:
                import av
                # PyAV codec fallback check
                logger.info("opuslib not found; checked PyAV")
            except Exception:
                pass
            logger.warning("Opus library bindings not present in Python environment; codec set to raw PCM passthrough mode")

    def encode(self, pcm_bytes: bytes) -> bytes:
        """
        Encodes 16-bit PCM audio frame to Opus.
        """
        if self.has_opus and self.encoder:
            try:
                return self.encoder.encode(pcm_bytes, SAMPLES_PER_FRAME)
            except Exception as e:
                logger.error(f"Opus encoding error: {e}")
                return pcm_bytes
        # Fallback passthrough
        return pcm_bytes

    def decode(self, opus_bytes: Optional[bytes]) -> bytes:
        """
        Decodes Opus frame to 16-bit PCM audio.
        If opus_bytes is None, performs Packet Loss Concealment (PLC).
        """
        if self.has_opus and self.decoder:
            try:
                if opus_bytes is None:
                    # Opus PLC decode
                    return self.decoder.decode(b"", SAMPLES_PER_FRAME, decode_fec=True)
                return self.decoder.decode(opus_bytes, SAMPLES_PER_FRAME)
            except Exception as e:
                logger.error(f"Opus decoding error: {e}")
                return b"\x00" * (SAMPLES_PER_FRAME * 2 * self.channels)

        # Fallback passthrough or silence for PLC
        if opus_bytes is None:
            return b"\x00" * (SAMPLES_PER_FRAME * 2 * self.channels)
        return opus_bytes
