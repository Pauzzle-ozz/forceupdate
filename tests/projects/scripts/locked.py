# /// script
# requires-python = ">=3.11"
# dependencies = ["flask>=2.3,<3"]
# ///
"""Un script verrouillé par « uv lock --script locked.py » : locked.py.lock."""

import flask

print(flask)
