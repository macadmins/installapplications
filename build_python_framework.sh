#!/bin/bash
#
# Build script for Python 3 framework for InstallApplications
# Taken from https://github.com/munki/munki/blob/Munki3dev/code/tools/build_python_framework.sh

TOOLSDIR=$(dirname $0)
REQUIREMENTS="${TOOLSDIR}/py3_requirements.txt"
PYTHON_VERSION=3.7.4
CODEDIR=$(dirname "${TOOLSDIR}")
MUNKIROOT=$(dirname "${CODEDIR}")

# Sanity checks.
GIT=$(which git)
WHICH_GIT_RESULT="$?"
if [ "${WHICH_GIT_RESULT}" != "0" ]; then
    echo "Could not find git in command path. Maybe it's not installed?" 1>&2
    echo "You can get a Git package here:" 1>&2
    echo "    https://git-scm.com/download/mac"
    exit 1
fi
if [ ! -f "${REQUIREMENTS}" ]; then
    echo "Missing requirements file at ${REQUIREMENTS}." 1>&2
    exit 1
fi

# clone our relocatable-python tool
PYTHONTOOLDIR="/tmp/relocatable-python-git"
if [ -d "${PYTHONTOOLDIR}" ]; then
    rm -rf "${PYTHONTOOLDIR}"
fi
echo "Cloning relocatable-python tool from github..."
git clone https://github.com/gregneagle/relocatable-python.git "${PYTHONTOOLDIR}"
CLONE_RESULT="$?"
if [ "${CLONE_RESULT}" != "0" ]; then
    echo "Error cloning relocatable-python tool repo: ${CLONE_RESULT}" 1>&2
    exit 1
fi

# remove existing Python.framework if present
if [ -d "${MUNKIROOT}/payload/Library/installapplications/Python.framework" ]; then
    rm -rf "${MUNKIROOT}/payload/Library/installapplications/Python.framework"
fi

# build the framework
"${PYTHONTOOLDIR}/make_relocatable_python_framework.py" \
    --python-version "${PYTHON_VERSION}" \
    --pip-requirements "${REQUIREMENTS}" \
    --destination "${MUNKIROOT}"

# move the framework
echo "Moving Python.framework to InstallApplications payload folder"
mv "${MUNKIROOT}/Python.framework" "${MUNKIROOT}/payload/Library/installapplications"
