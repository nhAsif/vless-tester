import socket
import ssl
import argparse
import sys

def test_connection(ip, port, sni, host, use_tls, path="/"):
    """
    Connects to an IP/Port and sends a request with a spoofed SNI and Host header.
    """
    print(f"[*] Researching connection to {ip}:{port}...")
    print(f"[*] Using Spoofed SNI: {sni if use_tls else 'N/A'}")
    print(f"[*] Using Spoofed Host Header: {host}")

    try:
        # 1. Establish raw TCP connection
        sock = socket.create_connection((ip, port), timeout=10)
        print("[+] TCP Connection established.")

        # 2. Wrap with TLS if requested
        if use_tls:
            context = ssl.create_default_context()
            # This is the "Spoofing" part for TLS:
            # We tell the SSL module to use the spoofed SNI during the handshake.
            sock = context.wrap_socket(sock, server_hostname=sni)
            print(f"[+] TLS Handshake successful with SNI: {sni}")

        # 3. Construct raw HTTP Request (simulating a WebSocket upgrade or simple GET)
        # Using HTTP/1.1 requires the 'Host' header.
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: SNI-Tester/1.0\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"\r\n"
        )

        # 4. Send the request
        sock.sendall(request.encode())
        print("[+] Request sent.")

        # 5. Read response
        response = sock.recv(4096)
        print("\n--- [ Server Response ] ---")
        try:
            print(response.decode(errors='replace'))
        except Exception:
            print(response)
        print("---------------------------\n")

        sock.close()
        print("[+] Connection closed.")

    except Exception as e:
        print(f"[!] Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Educational SNI/Host Spoofing Tester")
    parser.add_argument("--ip", required=True, help="Target IP address (The server you are really connecting to)")
    parser.add_argument("--port", type=int, default=80, help="Port (80 for HTTP, 443 for HTTPS/TLS)")
    parser.add_argument("--sni", default="Instagram.com", help="Hostname to use for TLS SNI")
    parser.add_argument("--host", default="Instagram.com", help="Hostname to use for HTTP Host Header")
    parser.add_argument("--path", default="/", help="Request path (e.g. /vless/)")
    parser.add_argument("--tls", action="store_true", help="Enable TLS (Use for port 443)")

    args = parser.parse_args()

    test_connection(
        ip=args.ip,
        port=args.port,
        sni=args.sni,
        host=args.host,
        use_tls=args.tls,
        path=args.path
    )
