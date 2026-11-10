"""Unix-socket API. The socket is not published on TCP or mounted in workers."""
import argparse
import fcntl
import http.client
import json
import os
import socket
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler

from updater.runner import Updater


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=40)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def handler(updater):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond("GET")

        def do_POST(self):
            self.respond("POST")

        def log_message(self, *args):
            pass

        def respond(self, method):
            try:
                if method == "GET" and self.path == "/status":
                    data = updater.status()
                elif method == "POST":
                    size = int(self.headers.get("Content-Length", 0))
                    if not 0 < size <= 4096:
                        raise ValueError("Недопустимый размер запроса")
                    body = json.loads(self.rfile.read(size))
                    if self.path == "/check":
                        data = updater.check()
                    elif self.path == "/install":
                        data = updater.start(body.get("version"), str(body.get("actor", ""))[:128])
                    elif self.path == "/restore" and body.get("confirm_data_loss") is True:
                        data = updater.start(None, str(body.get("actor", ""))[:128], restore=True)
                    else:
                        raise ValueError("Неизвестная операция")
                else:
                    self.send_error(404)
                    return
                code = 200
            except (ValueError, KeyError, TypeError) as exc:
                data, code = {"detail": str(exc)}, 409
            except Exception:
                data, code = {"detail": "Не удалось выполнить запрос к службе обновлений"}, 500
            encoded = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/opt/fleet-manager")
    parser.add_argument("--state", default="/var/lib/fleet-updater")
    parser.add_argument("--runtime", default="/run/fleet-updater")
    parser.add_argument("--project", default="fleet-manager")
    parser.add_argument("--wait-seconds", type=int, default=900)
    parser.add_argument("--request", choices=["status", "check", "restore"])
    parser.add_argument("--confirm-data-loss", action="store_true")
    args = parser.parse_args()
    path = args.runtime + "/updater.sock"
    if args.request:
        connection = UnixConnection(path)
        if args.request == "restore" and not args.confirm_data_loss:
            parser.error("Восстановление заменит БД копией: требуется --confirm-data-loss")
        connection.request("GET" if args.request == "status" else "POST", "/" + args.request,
                           json.dumps({"actor": "server-console", "confirm_data_loss": args.confirm_data_loss}))
        response = connection.getresponse()
        print(response.read().decode())
        raise SystemExit(0 if response.status == 200 else 1)
    os.makedirs(args.state, mode=0o700, exist_ok=True)
    with open(args.state + "/updater.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        updater = Updater(args.root, args.state, args.runtime, args.project, args.wait_seconds)
        if os.path.exists(path):
            os.unlink(path)
        with Server(path, handler(updater)) as server:
            os.chmod(path, 0o600)
            def periodic():
                while True:
                    try:
                        updater.check()
                    except Exception:
                        pass
                    time.sleep(3600)
            threading.Thread(target=periodic, daemon=True).start()
            server.serve_forever()


if __name__ == "__main__":
    main()
