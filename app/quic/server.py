import os
import ssl
import hashlib
import asyncio
import logging
import datetime
from typing import Optional, Tuple
from app.quic.session import session_registry
from app.quic.voice_relay import voice_relay

logger = logging.getLogger("pulse_relay.quic.server")

CERT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "certs")
CERT_PATH = os.path.join(CERT_DIR, "cert.pem")
KEY_PATH = os.path.join(CERT_DIR, "key.pem")

def generate_self_signed_cert() -> Tuple[str, str, str]:
    """
    Generates a self-signed ECDSA TLS certificate if not already present.
    Returns (cert_path, key_path, sha256_fingerprint_hex).
    """
    os.makedirs(CERT_DIR, exist_ok=True)

    if not os.path.exists(CERT_PATH) or not os.path.exists(KEY_PATH):
        logger.info("Generating self-signed ECDSA TLS certificate for QUIC/WebTransport...")
        try:
            from cryptography import x509
            from cryptography.x509.oid import NameOID
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec

            key = ec.generate_private_key(ec.SECP256R1())
            
            subject = issuer = x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, "Pulse Relay LAN Server"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Pulse Relay"),
            ])
            
            # WebTransport self-signed certs must have validity <= 14 days
            import socket
            import ipaddress

            san_list = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(('10.255.255.255', 1))
                lan_ip_str = s.getsockname()[0]
                s.close()
                san_list.append(x509.IPAddress(ipaddress.ip_address(lan_ip_str)))
            except Exception:
                pass

            now = datetime.datetime.now(datetime.timezone.utc)
            cert = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now)
                .not_valid_after(now + datetime.timedelta(days=13))
                .add_extension(
                    x509.SubjectAlternativeName(san_list),
                    critical=False,
                )
                .sign(key, hashes.SHA256())
            )

            # Save key
            with open(KEY_PATH, "wb") as f:
                f.write(key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                ))

            # Save cert
            with open(CERT_PATH, "wb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))

            logger.info(f"Self-signed TLS certificate saved to {CERT_PATH}")
        except Exception as e:
            logger.error(f"Failed to generate certificate with cryptography: {e}")
            # Fallback mock cert path handling
            pass

    # Compute SHA-256 fingerprint hash for WebTransport serverCertificateHashes
    cert_hash_hex = ""
    if os.path.exists(CERT_PATH):
        try:
            from cryptography import x509
            with open(CERT_PATH, "rb") as f:
                cert_bytes = f.read()
                cert_obj = x509.load_pem_x509_certificate(cert_bytes)
                cert_hash_hex = cert_obj.fingerprint(hashes.SHA256()).hex()
        except Exception:
            # Hash directly from file bytes
            with open(CERT_PATH, "rb") as f:
                cert_hash_hex = hashlib.sha256(f.read()).hexdigest()

    return CERT_PATH, KEY_PATH, cert_hash_hex


class UDPProtocolWrapper:
    def __init__(self, transport, addr):
        self.transport = transport
        self.addr = addr

    def send_datagram(self, data: bytes):
        if self.transport:
            self.transport.sendto(data, self.addr)


class UDPVoiceDatagramProtocol(asyncio.DatagramProtocol):
    """
    UDP Datagram handler for real-time voice packets over UDP/QUIC datagram connection.
    """
    def __init__(self):
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        logger.info("UDP/QUIC Voice Relay Datagram Server listening on UDP socket")

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        from app.audio.packet import VoicePacket
        packet = VoicePacket.parse(data)
        sender_session = None

        if packet and packet.sender_id:
            sender_id = packet.sender_id
            sender_session = session_registry.get_session(sender_id)
            if not sender_session:
                sender_session = session_registry.register_session(
                    sender_id,
                    UDPProtocolWrapper(self.transport, addr)
                )
            else:
                sender_session.protocol = UDPProtocolWrapper(self.transport, addr)

        # Process and forward datagram to recipient peer
        voice_relay.process_datagram(data, sender_session=sender_session)


class QuicVoiceServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 4433):
        self.host = host
        self.port = port
        self.cert_path, self.key_path, self.cert_hash = generate_self_signed_cert()
        self.transport = None
        self.udp_protocol = None
        self.is_running = False

    async def start(self):
        logger.info(f"Starting QUIC Voice Relay Server on {self.host}:{self.port} (UDP)")
        loop = asyncio.get_running_loop()

        # Check if aioquic is available
        has_aioquic = False
        try:
            import aioquic
            from aioquic.asyncio import serve
            from aioquic.quic.configuration import QuicConfiguration
            has_aioquic = True
        except ImportError:
            logger.warning("aioquic not found in environment; running fallback UDP datagram voice transport")

        if has_aioquic:
            try:
                from aioquic.asyncio import serve
                from aioquic.quic.configuration import QuicConfiguration
                from aioquic.asyncio.protocol import QuicConnectionProtocol

                configuration = QuicConfiguration(
                    is_client=False,
                    max_datagram_frame_size=65536
                )
                configuration.load_cert_chain(self.cert_path, self.key_path)

                def create_protocol(*args, **kwargs):
                    protocol = QuicConnectionProtocol(*args, **kwargs)
                    return protocol

                await serve(
                    self.host,
                    self.port,
                    configuration=configuration,
                    create_protocol=create_protocol
                )
                logger.info(f"aioquic QUIC Datagram server active on {self.host}:{self.port}")
                self.is_running = True
                return
            except Exception as e:
                logger.error(f"Error launching aioquic server: {e}; initializing fallback UDP server")

        # Fallback / Dual UDP Datagram Server
        try:
            self.transport, self.udp_protocol = await loop.create_datagram_endpoint(
                lambda: UDPVoiceDatagramProtocol(),
                local_addr=(self.host, self.port)
            )
            self.is_running = True
            logger.info(f"UDP Voice Relay Datagram Server bound successfully to {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to bind UDP Voice Relay server on {self.host}:{self.port}: {e}")

    async def stop(self):
        if self.transport:
            self.transport.close()
            self.is_running = False
            logger.info("QUIC/UDP Voice Relay server stopped")

quic_server = QuicVoiceServer()
