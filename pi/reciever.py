import socket

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

    with conn:
        data = b""

        while True:
            chunk = conn.recv(1024)

            if not chunk:
                break

            data += chunk

        print(f"Received: {data!r}", flush=True)

        if data:
            with open(FILE, "ab") as f:
                f.write(data)

            print(f"Written to {FILE}", flush=True)

