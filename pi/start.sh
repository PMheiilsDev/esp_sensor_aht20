#!/bin/bash

source .venv/bin/activate
exec watchmedo auto-restart --patterns="pi/*.py" --recursive -- python3 pi/reciever.py
