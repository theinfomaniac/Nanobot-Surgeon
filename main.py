#!/usr/bin/env python3
"""
main.py - simple threaded HTTP requester

Usage example:
    python main.py https://example.com --threads 10 --requests 100 --delay 0.05
"""

import argparse
import threading
import queue
import time
import sys
import signal

try:
    import requests
except ImportError:
    print("This script requires the 'requests' library. Install with: pip install requests")
    sys.exit(1)


def parse_headers(header_list):
        headers = {}
        if not header_list:
                return headers
        for h in header_list:
                if ":" in h:
                        k, v = h.split(":", 1)
                        headers[k.strip()] = v.strip()
        return headers


def worker(name, q, url, method, session_kwargs, delay, timeout, counters, lock, stop_event):
        session = requests.Session()
        session.headers.update(session_kwargs.get("headers", {}))
        while not stop_event.is_set():
                try:
                        q.get_nowait()
                except queue.Empty:
                        break
                try:
                        resp = session.request(method=method, url=url, timeout=timeout, data=session_kwargs.get("data"))
                        with lock:
                                counters["sent"] += 1
                                if 200 <= resp.status_code < 400:
                                        counters["success"] += 1
                                else:
                                        counters["fail"] += 1
                                print(f"[{counters['sent']}] {name} -> {resp.status_code}")
                except Exception as e:
                        with lock:
                                counters["sent"] += 1
                                counters["fail"] += 1
                                print(f"[{counters['sent']}] {name} -> ERROR: {e}")
                finally:
                        q.task_done()
                if delay:
                        time.sleep(delay)


def main():
        parser = argparse.ArgumentParser(description="Send multiple HTTP requests concurrently using threads.")
        parser.add_argument("url", help="Target URL")
        parser.add_argument("--threads", "-t", type=int, default=4, help="Number of worker threads (default: 4)")
        parser.add_argument("--requests", "-n", type=int, default=20, help="Total number of requests to send (default: 20)")
        parser.add_argument("--delay", "-d", type=float, default=0.0, help="Delay (sec) between requests per thread (default: 0)")
        parser.add_argument("--timeout", type=float, default=10.0, help="Request timeout in seconds (default: 10)")
        parser.add_argument("--method", "-m", default="GET", help="HTTP method (GET, POST, etc.)")
        parser.add_argument("--header", "-H", action="append", help="Custom header, can be repeated. Format: 'Name: Value'")
        parser.add_argument("--data", help="Request body for POST/PUT requests")
        args = parser.parse_args()

        # Safety: avoid accidental large floods; you can override by editing the script if needed.
        if args.requests > 100000 and args.threads * args.requests > 1000000:
                print("Requested number of requests is very large. Aborting for safety.")
                sys.exit(1)

        q = queue.Queue()
        for _ in range(args.requests):
                q.put(1)

        headers = parse_headers(args.header)
        session_kwargs = {"headers": headers, "data": args.data}

        counters = {"sent": 0, "success": 0, "fail": 0}
        lock = threading.Lock()
        stop_event = threading.Event()

        def handle_sigint(signum, frame):
                stop_event.set()
                print("\nStopping workers...")

        signal.signal(signal.SIGINT, handle_sigint)

        threads = []
        start = time.perf_counter()
        for i in range(args.threads):
                t = threading.Thread(
                        target=worker,
                        args=(f"worker-{i+1}", q, args.url, args.method.upper(), session_kwargs, args.delay, args.timeout, counters, lock, stop_event),
                        daemon=True,
                )
                threads.append(t)
                t.start()

        try:
                # Wait for queue to be processed or for stop_event
                while any(t.is_alive() for t in threads):
                        time.sleep(0.1)
                        if stop_event.is_set():
                                break
                q.join()
        except KeyboardInterrupt:
                stop_event.set()
        finally:
                # ensure threads exit
                for t in threads:
                        t.join(timeout=1)

        elapsed = time.perf_counter() - start
        print("\n=== Summary ===")
        print(f"Total sent:    {counters['sent']}")
        print(f"Successful:    {counters['success']}")
        print(f"Failed/error:   {counters['fail']}")
        print(f"Elapsed (s):   {elapsed:.2f}")
        if elapsed > 0:
                print(f"Requests/sec:  {counters['sent'] / elapsed:.2f}")


if __name__ == "__main__":
        main()