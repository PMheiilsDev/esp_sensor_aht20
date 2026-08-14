source pi/.venv/bin/activate.sh
watchmedo auto-restart --patterns="pi/*.py" --recursive -- python3 pi/reciever.py
