import os
import sys
import json
import time
import asyncio
import socket
import logging
from typing import Optional

from app.audio.packet import VoicePacket, create_voice_packet
from app.audio.codec import OpusCodec, SAMPLES_PER_FRAME, SAMPLE_RATE, CHANNELS
from app.audio.jitter import JitterBuffer
from app.models.messages import MessageType, CallState

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("pulse_relay.client")

class NativeVoiceClient:
    def __init__(self, server_ip: str = "127.0.0.1", http_port: int = 8000, client_id: Optional[str] = None):
        self.server_ip = server_ip
        self.http_port = http_port
        self.client_id = client_id
        
        self.codec = OpusCodec()
        self.jitter_buffer = JitterBuffer()
        
        self.ws_url = f"ws://{server_ip}:{http_port}/ws"
        self.quic_port = 4433
        
        self.status = CallState.IDLE
        self.active_call_id: Optional[str] = None
        self.active_peer_id: Optional[str] = None
        self.is_muted = False
        
        # UDP socket for QUIC / UDP Datagram media
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setblocking(False)
        
        self.seq_num = 1000
        self.running = True

    async def start(self):
        try:
            import websockets
        except ImportError:
            logger.error("websockets library required for native python client. Install with `pip install websockets`")
            return

        logger.info(f"Connecting to Pulse Relay WebSocket signaling at {self.ws_url}...")
        url = self.ws_url
        if self.client_id:
            url += f"?client_id={self.client_id}"

        async with websockets.connect(url) as ws:
            self.ws = ws
            logger.info("Connected to signaling server!")
            
            # Start background loops
            receive_task = asyncio.create_task(self._listen_signaling())
            udp_recv_task = asyncio.create_task(self._listen_udp_media())
            audio_tx_task = asyncio.create_task(self._audio_transmitter_loop())
            
            # Interactive CLI loop
            await self._cli_loop()
            
            receive_task.cancel()
            udp_recv_task.cancel()
            audio_tx_task.cancel()

    async def _listen_signaling(self):
        try:
            async for message in self.ws:
                data = json.loads(message)
                msg_type = data.get("type")
                
                if msg_type == MessageType.REGISTER:
                    self.client_id = data.get("client_id")
                    self.quic_port = data.get("quic_port", 4433)
                    logger.info(f"==> Registered as: {self.client_id}")
                    logger.info(f"==> Server QUIC Port: {self.quic_port}")

                elif msg_type == MessageType.CLIENT_LIST:
                    clients = data.get("clients", [])
                    print("\n--- ONLINE CLIENTS ---")
                    for c in clients:
                        print(f"  • {c['id']} [{c['status']}]")
                    print("----------------------\n")

                elif msg_type == MessageType.CALL_INCOMING:
                    caller = data.get("client_id")
                    call_id = data.get("call_id")
                    self.active_call_id = call_id
                    self.active_peer_id = caller
                    self.status = CallState.RINGING
                    print(f"\n[!] INCOMING CALL from {caller} (Call ID: {call_id})")
                    print("Type 'A' to ACCEPT or 'R' to REJECT\n")

                elif msg_type == MessageType.QUIC_INFO:
                    call_id = data.get("call_id")
                    self.active_call_id = call_id
                    self.quic_port = data.get("quic_port", 4433)
                    self.status = CallState.QUIC_CONNECTING
                    logger.info(f"Connecting QUIC Voice stream to {self.server_ip}:{self.quic_port}...")
                    
                    # Send CALL_CONNECTED event to server
                    await self._send_signal({
                        "type": MessageType.CALL_CONNECTED,
                        "call_id": call_id
                    })
                    self.status = CallState.VOICE_ACTIVE
                    logger.info("==> VOICE CALL ACTIVE! Speak now.")

                elif msg_type == MessageType.CALL_END:
                    reason = data.get("reason", "Ended")
                    logger.info(f"Call ended: {reason}")
                    self.status = CallState.IDLE
                    self.active_call_id = None
                    self.active_peer_id = None

                elif msg_type == MessageType.MUTE:
                    peer = data.get("client_id")
                    muted = data.get("muted")
                    logger.info(f"Peer {peer} is now {'MUTED' if muted else 'UNMUTED'}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Signaling error: {e}")

    async def _send_signal(self, payload: dict):
        if hasattr(self, 'ws') and self.ws:
            await self.ws.send(json.dumps(payload))

    async def _audio_transmitter_loop(self):
        """
        Continuously transmits 20ms audio frames over QUIC DATAGRAM when call is active.
        """
        frame_bytes_pcm = SAMPLES_PER_FRAME * 2 * CHANNELS
        
        while self.running:
            if self.status == CallState.VOICE_ACTIVE and self.active_call_id:
                if not self.is_muted:
                    # Synthesize/capture 20ms audio PCM frame
                    pcm_frame = b"\x00" * frame_bytes_pcm  # PCM silence / Mic frame
                    opus_payload = self.codec.encode(pcm_frame)
                    
                    self.seq_num += 1
                    pkt = create_voice_packet(
                        call_id=self.active_call_id,
                        sender_id=self.client_id,
                        sequence=self.seq_num,
                        payload=opus_payload
                    )
                    
                    # Send QUIC DATAGRAM frame over UDP socket to Pulse Relay server
                    raw_data = pkt.serialize()
                    try:
                        self.udp_socket.sendto(raw_data, (self.server_ip, self.quic_port))
                    except Exception as e:
                        logger.error(f"Error sending QUIC DATAGRAM: {e}")
                
            await asyncio.sleep(0.02)  # 20 ms frame rate

    async def _listen_udp_media(self):
        """
        Listens for incoming QUIC DATAGRAM voice packets from Pulse Relay server.
        """
        loop = asyncio.get_running_loop()
        while self.running:
            try:
                data, addr = await loop.sock_recvfrom(self.udp_socket, 2048)
                pkt = VoicePacket.parse(data)
                if pkt and self.status == CallState.VOICE_ACTIVE:
                    self.jitter_buffer.push(pkt)
                    popped_pkt, is_plc = self.jitter_buffer.pop()
                    if popped_pkt:
                        pcm = self.codec.decode(popped_pkt.payload)
                    elif is_plc:
                        pcm = self.codec.decode(None)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.005)

    async def _cli_loop(self):
        print("=" * 60)
        print(" Pulse Relay Native CLI Client Commands:")
        print("   C <TARGET_ID> : Call client (e.g. C CLIENT-B)")
        print("   A             : Accept incoming call")
        print("   R             : Reject incoming call")
        print("   M             : Toggle Mute")
        print("   E             : End active call")
        print("   Q             : Quit")
        print("=" * 60)

        loop = asyncio.get_running_loop()
        while self.running:
            line = await loop.run_in_executor(None, input, "> ")
            line = line.strip()
            if not line:
                continue

            cmd = line[0].upper()
            if cmd == 'Q':
                self.running = False
                break
            elif cmd == 'C':
                parts = line.split()
                if len(parts) > 1:
                    target = parts[1]
                    logger.info(f"Calling {target}...")
                    await self._send_signal({"type": MessageType.CALL, "target_id": target})
                else:
                    print("Usage: C <TARGET_ID>")
            elif cmd == 'A':
                if self.status == CallState.RINGING and self.active_call_id:
                    await self._send_signal({"type": MessageType.CALL_ACCEPT, "call_id": self.active_call_id})
                else:
                    print("No incoming call to accept")
            elif cmd == 'R':
                if self.status == CallState.RINGING and self.active_call_id:
                    await self._send_signal({"type": MessageType.CALL_REJECT, "call_id": self.active_call_id, "reason": "User rejected"})
                else:
                    print("No incoming call to reject")
            elif cmd == 'M':
                self.is_muted = not self.is_muted
                logger.info(f"Mute status: {self.is_muted}")
                if self.active_call_id:
                    await self._send_signal({"type": MessageType.MUTE, "call_id": self.active_call_id, "muted": self.is_muted})
            elif cmd == 'E':
                if self.active_call_id:
                    await self._send_signal({"type": MessageType.CALL_END, "call_id": self.active_call_id})
                else:
                    print("No active call to end")

if __name__ == "__main__":
    server_ip = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    client_id = sys.argv[2] if len(sys.argv) > 2 else None
    
    client = NativeVoiceClient(server_ip=server_ip, client_id=client_id)
    try:
        asyncio.run(client.start())
    except KeyboardInterrupt:
        print("\nExiting Pulse Relay client.")
