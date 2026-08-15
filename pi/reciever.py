import socket
from datetime import datetime
import json

from conf import HOST, PORT, FILE

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

server.bind((HOST, PORT))
server.listen(5)

print(f"Listening on {HOST}:{PORT}", flush=True)

while True:
    print("Waiting for connection...", flush=True)

    conn, addr = server.accept()

    print(f"Connection from {addr}", flush=True)

    conn.settimeout(2.0)

    try:
        data = conn.recv(1024)

        print(f"Received: {data!r}", flush=True)

        if data:
            with open(FILE, "ab") as f:
                s = data.decode("ascii").strip()
                j = json.loads(s)

                j = {
                    "time": datetime.now().isoformat(),
                    **j
                }

                f.write(
                    (json.dumps(j) + "\n").encode("utf-8")
                )

            print(f"Written to {FILE}", flush=True)

    except socket.timeout:
        print("Timeout waiting for data", flush=True)

    except Exception as e:
        print(f"Error receiving data: {e}", flush=True)

    finally:
        conn.close()
        print("Connection closed", flush=True)

