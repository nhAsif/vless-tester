import asyncio
import json
import socket
import time
import argparse
import csv
import os
import sys
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse, parse_qs, unquote

from dotenv import load_dotenv
import aiohttp
from aiohttp_socks import ProxyConnector
from rich.console import Console

# Load environment variables from .env file
load_dotenv()
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn

console = Console()

@dataclass
class VLESSServer:
    raw_uri: str
    uuid: str
    address: str
    port: int
    flow: str = ""
    security: str = "none"
    sni: str = ""
    fp: str = ""
    alpn: str = ""
    transport: str = "tcp"
    path: str = ""
    serviceName: str = ""
    host: str = ""
    type: str = ""
    remark: str = ""
    
    # Benchmarking results
    latency_min: float = float('inf')
    latency_avg: float = 0.0
    latency_max: float = 0.0
    speed_mbps: float = 0.0
    status: str = "PENDING"
    error: str = ""

    def __post_init__(self):
        # Normalize some fields
        if not self.sni:
            self.sni = self.address

    def to_uri(self) -> str:
        from urllib.parse import quote
        params = [
            f"encryption=none",
            f"security={self.security}",
            f"type={self.transport}"
        ]
        if self.path:
            params.append(f"path={quote(self.path, safe='')}")
        if self.host:
            params.append(f"host={quote(self.host, safe='')}")
        if self.sni:
            params.append(f"sni={quote(self.sni, safe='')}")
        if self.fp:
            params.append(f"fp={quote(self.fp, safe='')}")
        if self.alpn:
            params.append(f"alpn={quote(self.alpn, safe='')}")
        if self.flow:
            params.append(f"flow={quote(self.flow, safe='')}")
        if self.serviceName:
            params.append(f"serviceName={quote(self.serviceName, safe='')}")
            
        query = "&".join(params)
        remark_str = f"#{quote(self.remark)}" if self.remark else ""
        return f"vless://{self.uuid}@{self.address}:{self.port}?{query}{remark_str}"

    def to_minimal_uri(self) -> str:
        from urllib.parse import quote
        params = [
            f"security={'tls' if self.security not in ['none', ''] else 'none'}",
            f"type={self.transport}",
            f"path={quote(self.path, safe='')}",
            f"host={quote(self.host, safe='')}"
        ]
            
        query = "&".join(params)
        # We exclude remark, encryption, sni, fp, alpn, flow as per "only include these fields"
        return f"vless://{self.uuid}@{self.address}:{self.port}?{query}"

    def to_darktunnel_uri(self) -> str:
        import base64
        import json
        data = {
            "type": "VMESS", # Using VMESS as per user example structure
            "name": self.remark if self.remark else f"{self.address}:{self.port}",
            "vmessTunnelConfig": {
                "v2rayConfig": {
                    "host": self.address,
                    "port": self.port,
                    "uuid": self.uuid,
                    "tls": self.security not in ["none", ""],
                    "wsPath": self.path,
                    "wsHeaderHost": self.host if self.host else ""
                }
            }
        }
        json_str = json.dumps(data)
        b64_str = base64.b64encode(json_str.encode()).decode()
        return f"darktunnel://{b64_str}"

def parse_vless(uri: str) -> Optional[VLESSServer]:
    try:
        if not uri.startswith("vless://"):
            return None
        
        # vless://uuid@host:port?query#fragment
        parsed = urlparse(uri)
        user_info = parsed.username
        address = parsed.hostname
        port = parsed.port
        
        if not user_info or not address or not port:
            return None
        
        query = parse_qs(parsed.query)
        params = {k: v[0] for k, v in query.items()}
        
        return VLESSServer(
            raw_uri=uri,
            uuid=user_info,
            address=address,
            port=int(port),
            flow=params.get("flow", ""),
            security=params.get("security", "none"),
            sni=params.get("sni", ""),
            fp=params.get("fp", ""),
            alpn=params.get("alpn", ""),
            transport=params.get("type", "tcp"),
            path=params.get("path", ""),
            serviceName=params.get("serviceName", ""),
            host=params.get("host", ""),
            type=params.get("type", "tcp"),
            remark=unquote(parsed.fragment)
        )
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to parse URI {uri[:50]}... : {e}[/yellow]")
        return None

def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

class SingBoxInstance:
    def __init__(self, server: VLESSServer, singbox_path: str):
        self.server = server
        self.singbox_path = singbox_path
        self.port = get_free_port()
        self.config_path = f"config_{uuid.uuid4().hex}.json"
        self.process = None

    def generate_config(self):
        outbound = {
            "type": "vless",
            "tag": "proxy",
            "server": self.server.address,
            "server_port": self.server.port,
            "uuid": self.server.uuid,
            "flow": self.server.flow if self.server.flow else None,
            "packet_encoding": "xudp"
        }

        tls_conf = {}
        if self.server.security in ["tls", "xtls", "reality"]:
            tls_conf["enabled"] = True
            tls_conf["server_name"] = self.server.sni
            tls_conf["utls"] = {
                "enabled": True,
                "fingerprint": self.server.fp if self.server.fp else "chrome"
            }
            if self.server.alpn:
                tls_conf["alpn"] = [a.strip() for a in self.server.alpn.split(",")]
            
            outbound["tls"] = tls_conf

        transport_conf = {}
        t_type = self.server.transport
        if t_type == "ws":
            transport_conf = {
                "type": "ws",
                "path": self.server.path,
                "headers": {"Host": self.server.host} if self.server.host else {}
            }
        elif t_type == "grpc":
            transport_conf = {
                "type": "grpc",
                "service_name": self.server.serviceName
            }
        elif t_type in ["http", "h2"]:
            transport_conf = {
                "type": "http",
                "host": [self.server.host] if self.server.host else [self.server.address],
                "path": self.server.path
            }
        
        if transport_conf:
            outbound["transport"] = transport_conf

        config = {
            "log": {"level": "error"},
            "inbounds": [{
                "type": "socks",
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "listen_port": self.port
            }],
            "outbounds": [outbound, {"type": "direct", "tag": "direct"}]
        }
        
        with open(self.config_path, "w") as f:
            json.dump(config, f)

    async def start(self):
        self.generate_config()
        try:
            self.process = await asyncio.create_subprocess_exec(
                self.singbox_path, "run", "-c", self.config_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            # Give it a moment to start
            await asyncio.sleep(1)
        except Exception as e:
            self.cleanup()
            raise e

    def cleanup(self):
        if self.process:
            try:
                self.process.terminate()
            except:
                pass
        if os.path.exists(self.config_path):
            os.remove(self.config_path)

async def benchmark_server(server: VLESSServer, args: argparse.Namespace, semaphore: asyncio.Semaphore, progress, task_id):
    async with semaphore:
        sb = SingBoxInstance(server, args.singbox_path)
        try:
            await sb.start()
            
            # Latency Test
            latencies = []
            connector = ProxyConnector.from_url(f"socks5://127.0.0.1:{sb.port}")
            async with aiohttp.ClientSession(connector=connector) as session:
                for _ in range(3):
                    start_time = time.time()
                    try:
                        async with session.get(args.test_url, timeout=args.timeout) as response:
                            await response.release()
                            latencies.append((time.time() - start_time) * 1000)
                    except Exception:
                        latencies.append(None)
                
                valid_latencies = [l for l in latencies if l is not None]
                if not valid_latencies:
                    server.status = "FAILED"
                    server.error = "Latency test failed"
                else:
                    server.latency_min = min(valid_latencies)
                    server.latency_max = max(valid_latencies)
                    server.latency_avg = sum(valid_latencies) / len(valid_latencies)
                    
                    # Speed Test
                    speed_url = "https://cachefly.cachefly.net/1mb.test" # 1MB file
                    start_time = time.time()
                    try:
                        async with session.get(speed_url, timeout=args.timeout) as response:
                            content = await response.read()
                            duration = time.time() - start_time
                            size_mb = len(content) * 8 / (1024 * 1024) # bits to Mbits
                            server.speed_mbps = size_mb / duration
                            server.status = "SUCCESS"
                    except Exception as e:
                        server.status = "PARTIAL" # Latency OK, Speed failed
                        server.error = f"Speed test failed: {str(e)[:30]}"
            
        except Exception as e:
            server.status = "ERROR"
            server.error = str(e)[:50]
        finally:
            sb.cleanup()
            progress.update(task_id, advance=1)

async def tcp_ping(server: VLESSServer, timeout: int) -> Optional[float]:
    start = time.time()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(server.address, server.port),
            timeout=timeout
        )
        latency = (time.time() - start) * 1000
        writer.close()
        try:
            await writer.wait_closed()
        except:
            pass
        return latency
    except:
        return None

async def pre_filter_servers(servers: List[VLESSServer], timeout: int, workers: int, progress: Progress) -> List[VLESSServer]:
    task_id = progress.add_task("[yellow]Pre-filtering dead hosts (TCP Ping)...", total=len(servers))
    semaphore = asyncio.Semaphore(workers * 10) # Higher concurrency for simple TCP ping
    
    async def check(s):
        async with semaphore:
            latency = await tcp_ping(s, timeout)
            progress.update(task_id, advance=1)
            if latency is not None:
                s.latency_avg = latency
                s.status = "ALIVE"
                return s
            return None

    results = await asyncio.gather(*(check(s) for s in servers))
    alive_servers = [r for r in results if r is not None]
    progress.remove_task(task_id)
    return alive_servers

async def send_telegram_notification(servers: List[VLESSServer], token: str, chat_id: str, minimal: bool = False, darktunnel: bool = False):
    def escape_md(text):
        # Characters reserved in MarkdownV2: _ * [ ] ( ) ~ ` > # + - = | { } . !
        # Added | and others to the list
        escape_chars = r'_*[]()~`>#+-=|{}.!'
        return "".join('\\' + c if c in escape_chars else c for c in text)

    header = "🚀 *Top VLESS Servers*\n\n"
    body = ""
    for i, s in enumerate(servers):
        # Escape EVERYTHING that isn't a Markdown symbol
        idx = escape_md(str(i+1))
        addr = escape_md(s.address)
        lat = escape_md(f"{s.latency_avg:.1f}")
        speed = escape_md(f"{s.speed_mbps:.1f}")
        pipe = escape_md("|")
        body += f"{idx}\\. `{addr}` {pipe} {lat}ms {pipe} {speed}Mbps\n"
    
    body += "\n🔗 *Raw URIs:*\n"
    for s in servers:
        if darktunnel:
            uri = s.to_darktunnel_uri()
        elif minimal:
            uri = s.to_minimal_uri()
        else:
            uri = s.to_uri()
        body += f"`{escape_md(uri)}`\n\n"

    full_message = header + body
    if len(full_message) > 4000:
        truncated = full_message[:3980]
        # Count backticks to see if we're inside a code block
        if truncated.count('`') % 2 != 0:
            truncated += "`"
        full_message = truncated + "\\.\\.\\."

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json={
                "chat_id": chat_id,
                "text": full_message,
                "parse_mode": "MarkdownV2"
            }) as response:
                if response.status == 200:
                    console.print("[green]Telegram notification sent successfully.[/green]")
                else:
                    err = await response.text()
                    console.print(f"[red]Failed to send Telegram notification: {err}[/red]")
        except Exception as e:
            console.print(f"[red]Error sending Telegram notification: {e}[/red]")

async def main():
    parser = argparse.ArgumentParser(description="VLESS Server Benchmarker")
    parser.add_argument("--url", default="https://github.com/Epodonios/v2ray-configs/raw/main/Splitted-By-Protocol/vless.txt", help="Config list URL")
    parser.add_argument("--file", help="Local config list file")
    parser.add_argument("--timeout", type=int, default=10, help="Timeout per test")
    parser.add_argument("--workers", type=int, default=10, help="Max concurrent testers")
    parser.add_argument("--top", type=int, default=10, help="Number of top servers to export")
    parser.add_argument("--minimal", action="store_true", help="Export top servers in minimal VLESS URI format")
    parser.add_argument("--darktunnel", action="store_true", help="Export top servers in Darktunnel format")
    parser.add_argument("--custom-wshost", help="Override WebSocket Host header for all servers")
    parser.add_argument("--skip-ping", action="store_true", help="Skip initial TCP ping sweep")
    parser.add_argument("--singbox-path", default="/usr/bin/sing-box", help="Path to sing-box binary")
    parser.add_argument("--test-url", default="http://www.gstatic.com/generate_204", help="URL for latency test")
    parser.add_argument("--show-all", action="store_true", help="Show all benchmarked servers in the table")
    parser.add_argument("--ping-only", action="store_true", help="Only perform TCP ping sweep and save top results")
    args = parser.parse_args()

    if not args.ping_only and not os.path.exists(args.singbox_path):
        console.print(f"[red]Error: sing-box not found at {args.singbox_path}[/red]")
        sys.exit(1)

    if args.file:
        if not os.path.exists(args.file):
            console.print(f"[red]Error: File {args.file} not found.[/red]")
            sys.exit(1)
        console.print(f"[cyan]Reading config list from {args.file}...[/cyan]")
        with open(args.file, "r") as f:
            content = f.read()
    else:
        console.print(f"[cyan]Fetching config list from {args.url}...[/cyan]")
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(args.url) as response:
                    content = await response.text()
            except Exception as e:
                console.print(f"[red]Failed to fetch URL: {e}[/red]")
                sys.exit(1)

    # Detect and decode base64 if necessary
    import base64
    try:
        decoded = base64.b64decode(content, validate=True).decode('utf-8')
        if "vless://" in decoded:
            content = decoded
    except Exception:
        pass

    lines = content.splitlines()
    all_servers = []
    for line in lines:
        s = parse_vless(line.strip())
        if s:
            if args.custom_wshost:
                s.host = args.custom_wshost
            all_servers.append(s)

    console.print(f"[green]Found {len(all_servers)} VLESS servers.[/green]")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        # Phase 1: Pre-filtering
        if not args.skip_ping:
            alive_servers = await pre_filter_servers(all_servers, 3, args.workers, progress)
            console.print(f"[green]Filtered {len(all_servers) - len(alive_servers)} dead hosts. {len(alive_servers)} servers remaining.[/green]")
        else:
            alive_servers = all_servers
            console.print(f"[yellow]Skipping TCP ping sweep. Benchmarking all {len(alive_servers)} servers.[/yellow]")
        
        if not alive_servers:
            console.print("[red]No alive servers found.[/red]")
            return

        # Phase 2: Ping Only Mode
        if args.ping_only:
            sorted_ping = sorted(alive_servers, key=lambda x: x.latency_avg)
            
            table = Table(title=f"VLESS Ping Results (Top {args.top})")
            table.add_column("Rank", justify="right", style="cyan")
            table.add_column("Host", style="magenta")
            table.add_column("Port", justify="right")
            table.add_column("Latency (ms)", justify="right")
            
            display_limit = min(args.top, len(sorted_ping))
            for i in range(display_limit):
                s = sorted_ping[i]
                table.add_row(str(i+1), s.address[:50], str(s.port), f"{s.latency_avg:.2f}")
            
            console.print(table)
            
            with open("results.txt", "w") as f:
                for s in sorted_ping[:args.top]:
                    if args.darktunnel:
                        uri = s.to_darktunnel_uri()
                    elif args.minimal:
                        uri = s.to_minimal_uri()
                    else:
                        uri = s.to_uri()
                    f.write(f"{uri}\n")
            
            console.print(f"[green]Top {display_limit} configs saved to results.txt ranked by latency.[/green]")
            return

        # Phase 2: Full Benchmarking
        semaphore = asyncio.Semaphore(args.workers)
        task_id = progress.add_task("[cyan]Benchmarking alive servers...", total=len(alive_servers))
        tasks = [benchmark_server(s, args, semaphore, progress, task_id) for s in alive_servers]
        await asyncio.gather(*tasks)

    # Sorting
    sorted_servers = sorted(
        alive_servers,
        key=lambda x: (
            0 if x.status == "SUCCESS" else (1 if x.status == "PARTIAL" else 2),
            x.latency_avg if x.latency_avg > 0 else float('inf')
        )
    )

    # Display Results
    table = Table(title=f"VLESS Benchmark Results (Top {50 if not args.show_all else 'All'})")
    table.add_column("Rank", justify="right", style="cyan")
    table.add_column("Host", style="magenta")
    table.add_column("Port", justify="right")
    table.add_column("TLS", style="green")
    table.add_column("Transport", style="blue")
    table.add_column("Latency Avg (ms)", justify="right")
    table.add_column("Speed (Mbps)", justify="right")
    table.add_column("Status", style="bold")

    display_limit = len(sorted_servers) if args.show_all else min(50, len(sorted_servers))
    for i in range(display_limit):
        s = sorted_servers[i]
        latency_str = f"{s.latency_avg:.2f}" if s.latency_avg != 0 else "-"
        speed_str = f"{s.speed_mbps:.2f}" if s.speed_mbps != 0 else "-"
        status_style = "green" if s.status == "SUCCESS" else "yellow" if s.status == "PARTIAL" else "red"
        
        table.add_row(
            str(i+1),
            s.address[:30],
            str(s.port),
            s.security,
            s.transport,
            latency_str,
            speed_str,
            f"[{status_style}]{s.status}[/{status_style}]"
        )
    
    console.print(table)
    if not args.show_all and len(sorted_servers) > 50:
        console.print(f"[italic]... {len(sorted_servers) - 50} more servers omitted. Use --show-all to see everything.[/italic]")

    # Export to CSV
    with open("results.csv", "w", newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Rank", "Host", "Port", "TLS", "Transport", "Latency Avg", "Speed Mbps", "Status", "Error"])
        for i, s in enumerate(sorted_servers):
            writer.writerow([i+1, s.address, s.port, s.security, s.transport, s.latency_avg, s.speed_mbps, s.status, s.error])
    
    console.print(f"[green]Results exported to results.csv[/green]")

    # Export top N
    top_working = [s for s in sorted_servers if s.status in ["SUCCESS", "PARTIAL"]][:args.top]
    if top_working:
        with open("top_servers.txt", "w") as f:
            for s in top_working:
                if args.darktunnel:
                    uri = s.to_darktunnel_uri()
                elif args.minimal:
                    uri = s.to_minimal_uri()
                else:
                    uri = s.to_uri()
                f.write(f"{uri}\n")
        console.print(f"[green]Top {len(top_working)} working configs exported to top_servers.txt[/green]")

        # Telegram Notification
        tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
        tg_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if tg_token and tg_chat_id:
            await send_telegram_notification(top_working, tg_token, tg_chat_id, minimal=args.minimal, darktunnel=args.darktunnel)


if __name__ == "__main__":
    asyncio.run(main())
