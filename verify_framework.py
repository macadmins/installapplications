"""Smoke-test the built framework, including offline pip bootstrap paths."""

import hashlib
import importlib.metadata
import os
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import certifi
import objc
import requests
import xattr
import yaml
from packaging.version import Version


# emSign ECC Root CA - G3 and AAA Certificate Services (cross-sign path),
# removed by certifi 2026.10.19. Other emSign roots
# remain trusted by that release and must not be rejected just by their names.
REVOKED_ROOTS = {
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b",
    "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4",
}
PIP_CHECK = """
import hashlib
import ssl
import pip
from pip._vendor import certifi
if tuple(map(int, pip.__version__.split('.'))) < (26, 2, 2):
    raise RuntimeError('Vulnerable pip: ' + pip.__version__)
context = ssl.create_default_context(cafile=certifi.where())
if {revoked!r} & {{hashlib.sha256(c).hexdigest() for c in context.get_ca_certs(binary_form=True)}}:
    raise RuntimeError('pip still trusts the compromised emSign root')
print('Verified pip', pip.__version__, certifi.where(), flush=True)
""".format(revoked=REVOKED_ROOTS)


def run(*args):
    subprocess.run(args, check=True)


def check_context(context):
    fingerprints = {
        hashlib.sha256(cert).hexdigest()
        for cert in context.get_ca_certs(binary_form=True)
    }
    if not fingerprints or REVOKED_ROOTS & fingerprints:
        raise RuntimeError("Missing CA bundle or compromised emSign root still trusted")


def main():
    print(f"Verifying framework: {sys.version}", flush=True)
    for package, minimum in (("certifi", "2026.10.19"), ("pip", "26.2.2")):
        version = importlib.metadata.version(package)
        if Version(version) < Version(minimum):
            raise RuntimeError(f"{package} {version} is older than {minimum}")
        print(f"Verified {package} {version}", flush=True)

    if os.environ.get("SSL_CERT_FILE") != certifi.where():
        raise RuntimeError("sitecustomize did not select the bundled certifi CA store")
    check_context(ssl.create_default_context())
    check_context(ssl.create_default_context(cafile=certifi.where()))
    run(sys.executable, "-I", "-c", PIP_CHECK)
    run(sys.executable, "-I", "-m", "pip", "check")
    # Exercise relocated console scripts as well as python -m entry points.
    run(str(Path(sys.prefix) / "bin/pip"), "--version")
    run(str(Path(sys.prefix) / "bin/virtualenv"), "--version")

    with tempfile.TemporaryDirectory(prefix="macadmins-python-verify-") as temporary:
        root = Path(temporary)
        # Neither command may fetch a newer pip to hide an outdated seed wheel.
        run(sys.executable, "-I", "-m", "venv", str(root / "venv"))
        run(str(root / "venv/bin/python"), "-I", "-c", PIP_CHECK)
        run(
            sys.executable, "-I", "-m", "virtualenv",
            "--no-download", "--no-periodic-update",
            "--app-data", str(root / "app-data"), str(root / "virtualenv"),
        )
        run(str(root / "virtualenv/bin/python"), "-I", "-c", PIP_CHECK)

    for url in ("https://www.python.org/", "https://pypi.org/simple/pip/"):
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTPS check failed: {url}")
        requests.get(url, timeout=30).raise_for_status()
        print(f"Verified stdlib and Requests HTTPS: {url}", flush=True)
    print("Framework verification passed", flush=True)


if __name__ == "__main__":
    main()
