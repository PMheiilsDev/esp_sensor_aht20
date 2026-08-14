import socket

HOST = "0.0.0.0"
PORT = 5050
FILE = "/home/pi/data.txt"

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(1)

    print(f"Listening on {HOST}:{PORT}")

    while True:
        conn, addr = server.accept()

        with conn:
            print(f"Connection from {addr}")

            data = conn.recv(1024)

            if data:
                message = data.decode("utf-8", errors="replace")
                print(f"Received: {message}")

                with open(FILE, "a") as f:
                    f.write(message + "\n")

