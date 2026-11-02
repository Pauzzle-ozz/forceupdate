"""Un script sans bloc PEP 723 : forceupdate lit ses imports, sans version."""

import json
import os

import helpers
import requests
from dateutil import parser
from flask import Flask

try:
    import jinja2
except ImportError:
    jinja2 = None

print(json, os, requests, parser, Flask, helpers, jinja2)
