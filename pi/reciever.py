import socket

from conf import HOST, PORT, FILE

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)

    print(f"Listening on {HOST}:{PORT}", flush=True)

    while True:
        conn, addr = server.accept()

        print(f"Connection from {addr}", flush=True)

        with conn:
            chunks = []

            while True:
                data = conn.recv(1024)

                if not data:
                    break

                chunks.append(data)

            message = b"".join(chunks).decode(
                "utf-8",
                errors="replace"
            )

            print(f"Received: {message}", flush=True)

            with open(FILE, "a") as f:
                f.write(message + "\n")

