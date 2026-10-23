#!/bin/zsh
# Install fixed trust bundles without using the installer's pip online.
set -eu
set -o pipefail

FRAMEWORK="$1"
PYTHON_VERSION="$2"
RP_EXTRACT="$3"
TOOLSDIR="${0:A:h}"
PYTHON_BIN="${FRAMEWORK}/Versions/${PYTHON_VERSION}/bin/python${PYTHON_VERSION}"
PIP_VERSION="26.2.2"
PIP_SHA256="fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
PIP_URL="https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-${PIP_VERSION}-py3-none-any.whl"
PIP_DIR="$(/usr/bin/mktemp -d /tmp/installapplications-pip.XXXXXX)"
trap '/bin/rm -rf "$PIP_DIR"' EXIT
PIP_WHEEL="${PIP_DIR}/pip-${PIP_VERSION}-py3-none-any.whl"

/usr/bin/curl --fail --location "$PIP_URL" -o "$PIP_WHEEL"
echo "${PIP_SHA256}  ${PIP_WHEEL}" | /usr/bin/shasum -a 256 -c -
"$PYTHON_BIN" -I "${TOOLSDIR}/update_ensurepip.py" "$PIP_WHEEL"
"$PYTHON_BIN" -I -m ensurepip --upgrade --default-pip
"$PYTHON_BIN" -I -m pip --isolated --disable-pip-version-check install \
    --no-cache-dir wheel -r "${TOOLSDIR}/requirements_recommended.txt"

# Extras are installed after the upstream helper's relocation pass.
/usr/bin/python3 -I - "$RP_EXTRACT" "$FRAMEWORK" "$PYTHON_VERSION" <<'PY'
import sys

sys.path.insert(0, sys.argv[1])
from locallibs.fix import fix_script_shebangs

if not fix_script_shebangs(sys.argv[2], sys.argv[3]):
    raise SystemExit("Failed to relocate installed console scripts")
PY

# python.org's compiled-in OpenSSL CA path does not follow a relocated
# framework. Use the framework's certifi bundle unless the operator overrides it.
/bin/cp "${TOOLSDIR}/framework_sitecustomize.py" \
    "${FRAMEWORK}/Versions/${PYTHON_VERSION}/lib/python${PYTHON_VERSION}/site-packages/sitecustomize.py"
