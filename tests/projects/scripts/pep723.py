#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "flask>=0.12",
#   "requests",
# ]
# ///
"""Un script à bloc PEP 723 : son bloc est son manifeste, comme pour « uv run »."""

import flask
import requests

print(flask, requests)
