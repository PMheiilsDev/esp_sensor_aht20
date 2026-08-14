source .venv/bin/activate
watchmedo auto-restart --patterns="pi/*.py" --recursive -- python3 pi/reciever.py
