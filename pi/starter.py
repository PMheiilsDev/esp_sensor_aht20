from threading import Thread

from website import app
import reciever
import direct_aht


def run_website():
    app.run(
        host="0.0.0.0",
        port=5001,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


def run_receiver():
    reciever.start()


def run_direct_aht():
    direct_aht.start()


if __name__ == "__main__":

    website_thread = Thread(
        target=run_website,
        name="website",
        daemon=True,
    )

    receiver_thread = Thread(
        target=run_receiver,
        name="receiver",
        daemon=True,
    )

    direct_aht_thread = Thread(
        target=run_direct_aht,
        name="direct_aht",
        daemon=True,
    )

    website_thread.start()
    receiver_thread.start()
    direct_aht_thread.start()

    # Keep starter.py alive while all threads run.
    website_thread.join()
    receiver_thread.join()
    direct_aht_thread.join()