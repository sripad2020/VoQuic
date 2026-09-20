import time
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("pulse_relay.audio.congestion")

STATE_NORMAL = "NORMAL"
STATE_CONGESTED = "CONGESTED"
STATE_RECOVERY = "RECOVERY"

class CongestionController:
    """
    Implements a Delay-Gradient Congestion Control (GCC-style) state machine.
    Tracks RTT, Packet Loss, and Delay Gradient (dD_k) to dynamically adjust frame pacing.
    """
    def __init__(self):
        self.state: str = STATE_NORMAL
        self.rtt_ms: float = 12.0
        self.loss_pct: float = 0.0
        self.delay_gradient_ms: float = 0.0
        
        # Historical timing measurements
        self.last_tx_time: Optional[float] = None
        self.last_rx_time: Optional[float] = None
        self.smoothed_gradient: float = 0.0
        
        # Pacing recommendations
        self.frame_pacing_ms: int = 20
        self.target_bitrate_kbps: int = 64
        self.last_state_change: float = time.time()

    def record_packet_event(self, tx_time_ms: float, rx_time_ms: float, loss_pct: float, rtt_ms: float) -> Dict[str, Any]:
        """
        Processes a packet transmission/reception event and updates congestion control state machine.
        """
        self.rtt_ms = rtt_ms
        self.loss_pct = loss_pct
        now = time.time()

        if self.last_tx_time is not None and self.last_rx_time is not None:
            delta_tx = tx_time_ms - self.last_tx_time
            delta_rx = rx_time_ms - self.last_rx_time
            
            # Delay gradient formula: dD = (t_rx,k - t_rx,k-1) - (t_tx,k - t_tx,k-1)
            raw_gradient = delta_rx - delta_tx
            # Exponential moving average filter (alpha = 0.2)
            self.smoothed_gradient = 0.8 * self.smoothed_gradient + 0.2 * raw_gradient
            self.delay_gradient_ms = round(max(-50.0, min(100.0, self.smoothed_gradient)), 2)

        self.last_tx_time = tx_time_ms
        self.last_rx_time = rx_time_ms

        # State Machine Evaluation
        prev_state = self.state

        if self.loss_pct >= 5.0 or self.delay_gradient_ms > 15.0 or self.rtt_ms > 120.0:
            self.state = STATE_CONGESTED
            self.frame_pacing_ms = 40  # Throttle transmission rate to 40ms per frame
            self.target_bitrate_kbps = 32
        elif self.state == STATE_CONGESTED and self.loss_pct < 2.0 and self.delay_gradient_ms <= 3.0:
            self.state = STATE_RECOVERY
            self.frame_pacing_ms = 25
            self.target_bitrate_kbps = 48
            self.last_state_change = now
        elif self.state == STATE_RECOVERY and (now - self.last_state_change) > 3.0:
            self.state = STATE_NORMAL
            self.frame_pacing_ms = 20
            self.target_bitrate_kbps = 64

        if prev_state != self.state:
            logger.info(f"Congestion State Transition: {prev_state} -> {self.state} (dD={self.delay_gradient_ms}ms, loss={self.loss_pct}%)")

        return self.get_telemetry()

    def get_telemetry(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "rtt_ms": round(self.rtt_ms, 1),
            "loss_pct": round(self.loss_pct, 1),
            "delay_gradient_ms": round(self.delay_gradient_ms, 1),
            "pacing_ms": self.frame_pacing_ms,
            "target_bitrate_kbps": self.target_bitrate_kbps
        }

congestion_controller = CongestionController()
