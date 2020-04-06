#!/bin/zsh
#
# Build script for Python 3 framework for InstallApplications
# Taken from https://github.com/munki/munki/blob/Munki3dev/code/tools/build_python_framework.sh

# IMPORTANT
# Run this with your current directory being the path where this script is located

TOOLSDIR=$(dirname $0)
REQUIREMENTS="${TOOLSDIR}/py3_requirements.txt"
PYTHON_VERSION=3.8.0
PYTHONTOOLDIR="/tmp/relocatable-python-git"
CONSOLEUSER=$(/usr/bin/stat -f "%Su" /dev/console)
FRAMEWORKDIR="/Library/installapplications"

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

# Create CPE framework path if not present
if [ ! -d "${FRAMEWORKDIR}" ]; then
    /usr/bin/sudo /bin/mkdir -p "${FRAMEWORKDIR}"
fi

# remove existing library Python.framework if present
if [ -d "${FRAMEWORKDIR}/Python.framework" ]; then
    /usr/bin/sudo /bin/rm -rf "${FRAMEWORKDIR}/Python.framework"
fi

# clone our relocatable-python tool
if [ -d "${PYTHONTOOLDIR}" ]; then
    /usr/bin/sudo /bin/rm -rf "${PYTHONTOOLDIR}"
fi
echo "Cloning relocatable-python tool from github..."
git clone https://github.com/gregneagle/relocatable-python.git "${PYTHONTOOLDIR}"
CLONE_RESULT="$?"
if [ "${CLONE_RESULT}" != "0" ]; then
    echo "Error cloning relocatable-python tool repo: ${CLONE_RESULT}" 1>&2
    exit 1
fi

# remove existing munki-pkg Python.framework if present
if [ -d "$TOOLSDIR/payload/${FRAMEWORKDIR}/Python.framework" ]; then
    /bin/rm -rf "$TOOLSDIR/payload/${FRAMEWORKDIR}/Python.framework"
fi

# build the framework
/usr/bin/sudo "${PYTHONTOOLDIR}/make_relocatable_python_framework.py" \
    --python-version "${PYTHON_VERSION}" \
    --pip-requirements "${REQUIREMENTS}" \
    --destination "${FRAMEWORKDIR}"

# move the framework
echo "Moving Python.framework to InstallApplications munki-pkg payload folder"
/usr/bin/sudo /bin/mv "${FRAMEWORKDIR}/Python.framework" "$TOOLSDIR/payload/${FRAMEWORKDIR}"

# take ownership of the payload folder
echo "Taking ownership of the file to not break git"
/usr/bin/sudo /usr/sbin/chown -R ${CONSOLEUSER}:wheel "$TOOLSDIR/payload/${FRAMEWORKDIR}/Python.framework"
