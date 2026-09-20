import json
import logging
import uuid
import random
from typing import Dict, Any, Optional
from fastapi import WebSocket, WebSocketDisconnect
from app.models.messages import MessageType, CallState, ClientInfo, SignalMessage

logger = logging.getLogger("pulse_relay.signaling")

class ConnectionManager:
    def __init__(self):
        # client_id -> { "websocket": WebSocket, "status": CallState, "room_id": Optional[str], "call_id": Optional[str] }
        self.clients: Dict[str, Dict[str, Any]] = {}
        # room_id -> set(client_ids)
        self.rooms: Dict[str, set] = {}
        # call_id -> { "caller_id": str, "target_id": str, "state": CallState }
        self.active_calls: Dict[str, Dict[str, Any]] = {}
        self.quic_host: str = "0.0.0.0"
        self.quic_port: int = 4433
        self.cert_hash: str = ""

    def set_quic_info(self, host: str, port: int, cert_hash: str):
        self.quic_host = host
        self.quic_port = port
        self.cert_hash = cert_hash

    async def connect(self, websocket: WebSocket, requested_id: Optional[str] = None) -> str:
        await websocket.accept()
        
        # Determine unique client_id
        if requested_id and requested_id not in self.clients:
            client_id = requested_id
        else:
            idx = 1
            client_id = f"CLIENT-{chr(64 + len(self.clients) + 1)}" if len(self.clients) < 26 else f"CLIENT-{len(self.clients) + 1}"
            while client_id in self.clients:
                idx += 1
                client_id = f"CLIENT-{idx}"
        
        self.clients[client_id] = {
            "websocket": websocket,
            "status": CallState.IDLE,
            "room_id": None,
            "call_id": None
        }
        logger.info(f"Client registered: {client_id}")
        
        # Send registration confirmation
        reg_msg = SignalMessage(
            type=MessageType.REGISTER,
            client_id=client_id,
            quic_host=self.quic_host,
            quic_port=self.quic_port,
            cert_hash=self.cert_hash
        )
        await websocket.send_text(reg_msg.model_dump_json())
        
        # Broadcast updated client list
        await self.broadcast_client_list()
        return client_id

    async def disconnect(self, client_id: str):
        if client_id in self.clients:
            client_data = self.clients[client_id]
            room_id = client_data.get("room_id")
            call_id = client_data.get("call_id")
            
            # Leave room if in any
            if room_id:
                await self._leave_room_internal(client_id, room_id)

            # If in a call, terminate it for the peer
            if call_id and call_id in self.active_calls:
                await self._end_call_internal(call_id, reason=f"{client_id} disconnected")
            
            del self.clients[client_id]
            logger.info(f"Client disconnected: {client_id}")
            await self.broadcast_client_list()

    async def broadcast_client_list(self):
        from app.models.messages import RoomInfo

        client_list = [
            ClientInfo(
                id=c_id,
                status=c_data["status"],
                room_id=c_data["room_id"],
                call_id=c_data["call_id"]
            )
            for c_id, c_data in self.clients.items()
        ]
        
        room_list = [
            RoomInfo(
                id=r_id,
                member_count=len(members),
                members=list(members)
            )
            for r_id, members in self.rooms.items()
        ]

        msg = SignalMessage(
            type=MessageType.CLIENT_LIST,
            clients=client_list,
            rooms=room_list
        )
        payload = msg.model_dump_json()
        
        for c_id, c_data in list(self.clients.items()):
            try:
                await c_data["websocket"].send_text(payload)
            except Exception as e:
                logger.error(f"Error sending client list to {c_id}: {e}")

    async def broadcast_room_update(self, room_id: str):
        if room_id not in self.rooms:
            return
        member_ids = list(self.rooms[room_id])
        members_info = [
            ClientInfo(
                id=m_id,
                status=self.clients[m_id]["status"],
                room_id=room_id,
                call_id=self.clients[m_id]["call_id"]
            )
            for m_id in member_ids if m_id in self.clients
        ]
        
        msg = SignalMessage(
            type=MessageType.ROOM_UPDATE,
            room_id=room_id,
            members=members_info
        )
        payload = msg.model_dump_json()

        for m_id in member_ids:
            if m_id in self.clients:
                try:
                    await self.clients[m_id]["websocket"].send_text(payload)
                except Exception as e:
                    logger.error(f"Error sending room update to {m_id}: {e}")

    async def handle_message(self, client_id: str, message_text: str):
        try:
            data = json.loads(message_text)
            msg = SignalMessage(**data)
        except Exception as e:
            logger.error(f"Invalid signal message from {client_id}: {e}")
            return

        msg_type = msg.type
        logger.info(f"Received {msg_type} from {client_id}: {data}")

        if msg_type == MessageType.CREATE_ROOM:
            await self._handle_create_room(client_id, msg.room_id)
        elif msg_type == MessageType.JOIN_ROOM:
            await self._handle_join_room(client_id, msg.room_id)
        elif msg_type == MessageType.LEAVE_ROOM:
            await self._handle_leave_room(client_id, msg.room_id)
        elif msg_type == MessageType.CALL:
            await self._handle_call(client_id, msg.target_id)
        elif msg_type == MessageType.CALL_ACCEPT:
            await self._handle_call_accept(client_id, msg.call_id)
        elif msg_type == MessageType.CALL_REJECT:
            await self._handle_call_reject(client_id, msg.call_id, msg.reason)
        elif msg_type == MessageType.CALL_CONNECTED:
            await self._handle_call_connected(client_id, msg.call_id)
        elif msg_type == MessageType.CALL_END:
            await self._handle_call_end(client_id, msg.call_id)
        elif msg_type == MessageType.MUTE:
            await self._handle_mute(client_id, msg.call_id, msg.muted)
        elif msg_type == MessageType.CHAT_MESSAGE:
            await self._handle_chat_message(client_id, msg.room_id, msg.text)
        elif msg_type == MessageType.EMOJI_REACTION:
            await self._handle_emoji_reaction(client_id, msg.room_id, msg.emoji)
        elif msg_type == MessageType.PING:
            await self._send_to(client_id, SignalMessage(type=MessageType.PONG))

    async def handle_binary_media(self, sender_id: str, raw_data: bytes):
        from app.audio.packet import VoicePacket
        packet = VoicePacket.parse(raw_data)
        if not packet:
            return
        
        sender_data = self.clients.get(sender_id)
        room_id = sender_data.get("room_id") if sender_data else None

        # Stealth Private Whisper Media Sub-Channel Isolation
        if packet.whisper_target_id:
            target_id = packet.whisper_target_id
            if target_id in self.clients:
                try:
                    await self.clients[target_id]["websocket"].send_bytes(raw_data)
                except Exception as e:
                    logger.error(f"Error forwarding whisper media to {target_id}: {e}")
            return

        # Multi-party room broadcast forwarding
        if room_id and room_id in self.rooms:
            for peer_id in list(self.rooms[room_id]):
                if peer_id != sender_id and peer_id in self.clients:
                    try:
                        await self.clients[peer_id]["websocket"].send_bytes(raw_data)
                    except Exception as e:
                        logger.error(f"Error forwarding multi-party media to {peer_id}: {e}")
        elif packet.call_id in self.active_calls:
            call_info = self.active_calls[packet.call_id]
            caller_id = call_info["caller_id"]
            target_id = call_info["target_id"]
            dest_id = target_id if sender_id == caller_id else caller_id
            
            if dest_id in self.clients:
                try:
                    await self.clients[dest_id]["websocket"].send_bytes(raw_data)
                except Exception as e:
                    logger.error(f"Error forwarding binary media to {dest_id}: {e}")

    async def _handle_chat_message(self, client_id: str, room_id: Optional[str], text: Optional[str]):
        target_room = room_id or self.clients.get(client_id, {}).get("room_id")
        call_id = self.clients.get(client_id, {}).get("call_id")
        if not text:
            return
        
        chat_signal = SignalMessage(
            type=MessageType.CHAT_MESSAGE,
            client_id=client_id,
            room_id=target_room,
            call_id=call_id,
            text=text
        )
        payload = chat_signal.model_dump_json()

        sent_to = set()
        if target_room and target_room in self.rooms:
            for peer_id in list(self.rooms[target_room]):
                if peer_id != client_id and peer_id in self.clients:
                    try:
                        await self.clients[peer_id]["websocket"].send_text(payload)
                        sent_to.add(peer_id)
                    except Exception as e:
                        logger.error(f"Error broadcasting chat message to {peer_id}: {e}")

        if call_id and call_id in self.active_calls:
            call_info = self.active_calls[call_id]
            dest_id = call_info["target_id"] if client_id == call_info["caller_id"] else call_info["caller_id"]
            if dest_id in self.clients and dest_id not in sent_to:
                try:
                    await self.clients[dest_id]["websocket"].send_text(payload)
                except Exception as e:
                    logger.error(f"Error sending chat message to call peer {dest_id}: {e}")

    async def _handle_emoji_reaction(self, client_id: str, room_id: Optional[str], emoji: Optional[str]):
        target_room = room_id or self.clients.get(client_id, {}).get("room_id")
        call_id = self.clients.get(client_id, {}).get("call_id")
        if not emoji:
            return
        
        emoji_signal = SignalMessage(
            type=MessageType.EMOJI_REACTION,
            client_id=client_id,
            room_id=target_room,
            call_id=call_id,
            emoji=emoji
        )
        payload = emoji_signal.model_dump_json()

        sent_to = set()
        if target_room and target_room in self.rooms:
            for peer_id in list(self.rooms[target_room]):
                if peer_id != client_id and peer_id in self.clients:
                    try:
                        await self.clients[peer_id]["websocket"].send_text(payload)
                        sent_to.add(peer_id)
                    except Exception as e:
                        logger.error(f"Error broadcasting emoji reaction to {peer_id}: {e}")

        if call_id and call_id in self.active_calls:
            call_info = self.active_calls[call_id]
            dest_id = call_info["target_id"] if client_id == call_info["caller_id"] else call_info["caller_id"]
            if dest_id in self.clients and dest_id not in sent_to:
                try:
                    await self.clients[dest_id]["websocket"].send_text(payload)
                except Exception as e:
                    logger.error(f"Error sending emoji reaction to call peer {dest_id}: {e}")

    async def _handle_create_room(self, client_id: str, requested_room_id: Optional[str]):
        room_id = requested_room_id or f"ROOM-{random.randint(100000, 999999)}"
        while room_id in self.rooms and not requested_room_id:
            room_id = f"ROOM-{random.randint(100000, 999999)}"

        if room_id not in self.rooms:
            self.rooms[room_id] = set()
        
        await self._join_room_internal(client_id, room_id)

    async def _handle_join_room(self, client_id: str, room_id: Optional[str]):
        if not room_id:
            await self._send_to(client_id, SignalMessage(type=MessageType.ERROR, reason="Room ID is required"))
            return
        
        if room_id not in self.rooms:
            self.rooms[room_id] = set()

        await self._join_room_internal(client_id, room_id)

    async def _join_room_internal(self, client_id: str, room_id: str):
        # Leave existing room if any
        existing_room = self.clients[client_id].get("room_id")
        if existing_room and existing_room != room_id:
            await self._leave_room_internal(client_id, existing_room)

        self.rooms[room_id].add(client_id)
        self.clients[client_id]["room_id"] = room_id
        if self.clients[client_id]["status"] == CallState.IDLE:
            self.clients[client_id]["status"] = CallState.IN_ROOM

        await self._send_to(client_id, SignalMessage(
            type=MessageType.JOIN_ROOM,
            room_id=room_id,
            client_id=client_id
        ))
        await self.broadcast_room_update(room_id)
        await self.broadcast_client_list()

    async def _handle_leave_room(self, client_id: str, room_id: Optional[str]):
        target_room = room_id or self.clients[client_id].get("room_id")
        if target_room:
            await self._leave_room_internal(client_id, target_room)

    async def _leave_room_internal(self, client_id: str, room_id: str):
        if room_id in self.rooms and client_id in self.rooms[room_id]:
            self.rooms[room_id].remove(client_id)
            if not self.rooms[room_id]:
                del self.rooms[room_id]
            else:
                await self.broadcast_room_update(room_id)

        self.clients[client_id]["room_id"] = None
        if self.clients[client_id]["status"] == CallState.IN_ROOM:
            self.clients[client_id]["status"] = CallState.IDLE

        await self._send_to(client_id, SignalMessage(
            type=MessageType.LEAVE_ROOM,
            room_id=room_id,
            client_id=client_id
        ))
        await self.broadcast_client_list()

    async def _handle_call(self, caller_id: str, target_id: Optional[str]):
        if not target_id or target_id not in self.clients:
            await self._send_to(caller_id, SignalMessage(
                type=MessageType.ERROR,
                reason="Target client unavailable or offline"
            ))
            return

        caller_data = self.clients[caller_id]
        target_data = self.clients[target_id]

        valid_states = (CallState.IDLE, CallState.IN_ROOM)
        if caller_data["status"] not in valid_states or target_data["status"] not in valid_states:
            await self._send_to(caller_id, SignalMessage(
                type=MessageType.ERROR,
                reason="One of the clients is already in an active call"
            ))
            return

        call_id = f"call_{uuid.uuid4().hex[:10]}"
        self.active_calls[call_id] = {
            "caller_id": caller_id,
            "target_id": target_id,
            "state": CallState.CALLING
        }

        caller_data["status"] = CallState.CALLING
        caller_data["call_id"] = call_id
        target_data["status"] = CallState.RINGING
        target_data["call_id"] = call_id

        # Send call initiation response with call_id back to caller
        await self._send_to(caller_id, SignalMessage(
            type=MessageType.CALL,
            client_id=caller_id,
            target_id=target_id,
            call_id=call_id
        ))

        # Notify target of incoming call
        await self._send_to(target_id, SignalMessage(
            type=MessageType.CALL_INCOMING,
            client_id=caller_id,
            target_id=target_id,
            call_id=call_id
        ))
        
        await self.broadcast_client_list()

    async def _handle_call_accept(self, target_id: str, call_id: Optional[str]):
        if not call_id or call_id not in self.active_calls:
            return
        
        call_info = self.active_calls[call_id]
        caller_id = call_info["caller_id"]
        
        call_info["state"] = CallState.ACCEPTED
        self.clients[caller_id]["status"] = CallState.ACCEPTED
        self.clients[target_id]["status"] = CallState.ACCEPTED

        # Bind call pairing in QUIC session registry for DATAGRAM relaying
        from app.quic.session import session_registry
        session_registry.bind_call(call_id, caller_id, target_id)

        # Send QUIC parameters to both caller and target
        quic_msg = SignalMessage(
            type=MessageType.QUIC_INFO,
            call_id=call_id,
            quic_host=self.quic_host,
            quic_port=self.quic_port,
            cert_hash=self.cert_hash,
            client_id=caller_id,
            target_id=target_id
        )

        await self._send_to(caller_id, quic_msg)
        await self._send_to(target_id, quic_msg)
        await self.broadcast_client_list()

    async def _handle_call_reject(self, target_id: str, call_id: Optional[str], reason: Optional[str]):
        if not call_id or call_id not in self.active_calls:
            return
        call_info = self.active_calls[call_id]
        caller_id = call_info["caller_id"]

        await self._send_to(caller_id, SignalMessage(
            type=MessageType.CALL_REJECT,
            call_id=call_id,
            reason=reason or "Call rejected by user"
        ))
        
        await self._end_call_internal(call_id, reason="Rejected")

    async def _handle_call_connected(self, client_id: str, call_id: Optional[str]):
        if not call_id or call_id not in self.active_calls:
            return
        call_info = self.active_calls[call_id]
        call_info["state"] = CallState.VOICE_ACTIVE

        caller_id = call_info["caller_id"]
        target_id = call_info["target_id"]

        self.clients[caller_id]["status"] = CallState.VOICE_ACTIVE
        self.clients[target_id]["status"] = CallState.VOICE_ACTIVE

        from app.quic.session import session_registry
        session_registry.bind_call(call_id, caller_id, target_id)

        connected_msg = SignalMessage(
            type=MessageType.CALL_CONNECTED,
            call_id=call_id
        )
        await self._send_to(caller_id, connected_msg)
        await self._send_to(target_id, connected_msg)
        await self.broadcast_client_list()

    async def _handle_call_end(self, client_id: str, call_id: Optional[str]):
        target_call_id = call_id
        if not target_call_id or target_call_id not in self.active_calls:
            target_call_id = self.clients.get(client_id, {}).get("call_id")

        if target_call_id and target_call_id in self.active_calls:
            await self._end_call_internal(target_call_id, reason=f"Ended by {client_id}")
        else:
            # Fallback search if call_id was not explicitly specified
            for cid, cinfo in list(self.active_calls.items()):
                if cinfo.get("caller_id") == client_id or cinfo.get("target_id") == client_id:
                    await self._end_call_internal(cid, reason=f"Ended by {client_id}")
                    break

    async def _handle_mute(self, client_id: str, call_id: Optional[str], muted: Optional[bool]):
        if not call_id or call_id not in self.active_calls:
            return
        call_info = self.active_calls[call_id]
        peer_id = call_info["target_id"] if call_info["caller_id"] == client_id else call_info["caller_id"]
        
        await self._send_to(peer_id, SignalMessage(
            type=MessageType.MUTE,
            client_id=client_id,
            call_id=call_id,
            muted=muted
        ))

    async def _end_call_internal(self, call_id: str, reason: str = "Call ended"):
        if call_id not in self.active_calls:
            return
        call_info = self.active_calls.pop(call_id)
        caller_id = call_info["caller_id"]
        target_id = call_info["target_id"]

        from app.quic.session import session_registry
        session_registry.unbind_call(call_id)

        end_msg = SignalMessage(
            type=MessageType.CALL_END,
            call_id=call_id,
            reason=reason
        )

        for c_id in (caller_id, target_id):
            if c_id in self.clients:
                self.clients[c_id]["status"] = CallState.IDLE
                self.clients[c_id]["call_id"] = None
                await self._send_to(c_id, end_msg)

        await self.broadcast_client_list()

    async def _send_to(self, client_id: str, message: SignalMessage):
        if client_id in self.clients:
            try:
                await self.clients[client_id]["websocket"].send_text(message.model_dump_json())
            except Exception as e:
                logger.error(f"Error sending message to {client_id}: {e}")

manager = ConnectionManager()
