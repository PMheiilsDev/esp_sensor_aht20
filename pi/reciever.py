import socket
from datetime import datetime
import json

from conf import HOST, PORT, DB_FILE
from db import init_db, get_db

def start():

    init_db()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    server.bind((HOST, PORT))
    server.listen(5)

    print(f"Listening on {HOST}:{PORT}", flush=True)

    while True:
        print("Waiting for connection...", flush=True)

        conn, addr = server.accept()

        print(f"Connection from {addr}", flush=True)

        conn.settimeout(5.0)

        try:

            # ------------------------------------------------
            # Receive until newline
            # ------------------------------------------------

            data = b""

            while b"\n" not in data:

                chunk = conn.recv(1024)

                if not chunk:
                    break

                data += chunk

            print(
                f"Received: {data!r}",
                flush=True
            )


            if data:

                # Only use the first complete line.
                line = data.split(b"\n", 1)[0]

                s = line.decode("utf-8")

                j = json.loads(s)


                # ------------------------------------------------
                # Add Pi timestamp
                # ------------------------------------------------

                j = {
                    "time": datetime.now().isoformat(),
                    **j
                }


                # ------------------------------------------------
                # Store
                # ------------------------------------------------

                with get_db() as conn:
                    conn.execute(
                        "INSERT INTO sensor_data (time, temperature, humidity, vbat, power_save) VALUES (?, ?, ?, ?, ?)",
                        (
                            j["time"],
                            float(j["temperature"]),
                            float(j["humidity"]),
                            float(j["vbat"]),
                            1 if j["power_save"] else 0
                        )
                    )
                    conn.commit()


                print(
                    f"Written to {DB_FILE}",
                    flush=True
                )


                # ------------------------------------------------
                # ACK only after successful write
                # ------------------------------------------------

                conn.sendall(b"OK\n")

                print(
                    "ACK sent",
                    flush=True
                )

        except socket.timeout:
            print("Timeout waiting for data", flush=True)

        except Exception as e:
            print(f"Error receiving data: {e}", flush=True)

        finally:
            conn.close()
            print("Connection closed", flush=True)


if __name__ == '__main__':
    start()

