# VLESS Benchmarker

A production-quality Python tool for fetching, filtering, and benchmarking VLESS proxy configurations using `sing-box`.

## Features

- **Asynchronous Execution:** Built with `asyncio` for high-performance concurrent testing.
- **Pre-filtering:** Uses high-speed TCP ping to quickly discard dead hosts.
- **Dynamic Configuration:** Automatically generates `sing-box` JSON configs for various transport types (TCP, WS, gRPC, HTTP) and security protocols (TLS, Reality).
- **Comprehensive Metrics:**
    - **Latency:** Measures RTT to a target URL (default: Google Connectivity Check).
    - **Speed:** Benchmarks download throughput in Mbps using a test file.
- **Rich CLI Interface:** Beautifully formatted tables and progress bars powered by `rich`.
- **Export Options:** Results are saved to `results.csv`, and the top N working configurations are exported to `top_servers.txt`.

## Prerequisites

- **Python 3.8+**
- **sing-box:** Ensure the `sing-box` binary is installed and available in your PATH (usually `/usr/bin/sing-box`).

## Installation

1. Clone or download this repository.
2. Install the required Python packages:

```bash
pip install -r requirements.txt
```

## Usage

Run the script with default settings:

```bash
python3 vless_benchmarker.py
```

### Advanced Options

```bash
usage: vless_benchmarker.py [-h] [--url URL] [--timeout TIMEOUT] [--workers WORKERS] 
                           [--top TOP] [--singbox-path SINGBOX_PATH] 
                           [--test-url TEST_URL] [--show-all]

options:
  -h, --help            show this help message and exit
  --url URL             Config list URL
  --timeout TIMEOUT     Timeout per test in seconds (default: 10)
  --workers WORKERS     Max concurrent testers (default: 10)
  --top TOP             Number of top servers to export (default: 10)
  --singbox-path PATH   Path to sing-box binary (default: /usr/bin/sing-box)
  --test-url URL        URL for latency test
  --show-all            Show all benchmarked servers in the table (default: Top 50)
```

### Examples

**Benchmark with 20 workers and a 5-second timeout:**
```bash
python3 vless_benchmarker.py --workers 20 --timeout 5
```

**Export the top 20 working servers:**
```bash
python3 vless_benchmarker.py --top 20
```

## Output

- **CLI Table:** A sorted list of servers based on status and latency.
- **results.csv:** Full benchmark data for all tested servers.
- **top_servers.txt:** A list of raw `vless://` URIs for the fastest working servers.

## License

MIT
