import os
import sys
import uvicorn
from app.quic.server import generate_self_signed_cert

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    
    # CLI flags: --ssl enables HTTPS mode, default is plain HTTP on port 8000
    use_ssl = "--ssl" in sys.argv or os.environ.get("USE_SSL", "0") == "1"
    
    if use_ssl:
        port = int(os.environ.get("HTTPS_PORT", 8443))
        cert_path, key_path, cert_hash = generate_self_signed_cert()
        ssl_cert = cert_path if os.path.exists(cert_path) else None
        ssl_key = key_path if os.path.exists(key_path) else None
        scheme = "https"
    else:
        port = int(os.environ.get("HTTP_PORT", 8000))
        ssl_cert = None
        ssl_key = None
        scheme = "http"

    print("=" * 65)
    print("           PULSE RELAY VOICE-OVER-QUIC SERVER")
    print("=" * 65)
    print(f" Protocol           : {scheme.upper()}")
    print(f" Web UI & Signaling : {scheme}://localhost:{port}")
    print(f" LAN Access         : {scheme}://<YOUR_LAN_IP>:{port}")
    print("-" * 65)
    if ssl_cert:
        print(" SSL / HTTPS        : ENABLED (Port 8443)")
        print(" ℹ️ Note for Mobile  : On mobile, tap 'Advanced' -> 'Proceed to site'")
    else:
        print(" SSL / HTTPS        : DISABLED (Default HTTP Mode on Port 8000)")
        print(" ℹ️ Note             : Open http://<YOUR_LAN_IP>:8000 in your browser.")
        print(" ℹ️ To Enable HTTPS  : python run.py --ssl")
    print("=" * 65)

    kwargs = {
        "host": host,
        "port": port,
        "reload": False,
        "log_level": "info"
    }

    if ssl_cert and ssl_key:
        kwargs["ssl_certfile"] = ssl_cert
        kwargs["ssl_keyfile"] = ssl_key

    uvicorn.run("app.main:app", **kwargs)
