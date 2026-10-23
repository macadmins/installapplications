"""Select the relocated framework's updated CA bundle for stdlib HTTPS."""

import os

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
