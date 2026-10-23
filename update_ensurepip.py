"""Replace ensurepip's bundled pip so offline venv creation uses fixed CAs."""

import ensurepip
import re
import shutil
import sys
from pathlib import Path


def main():
    wheel = Path(sys.argv[1])
    version = wheel.name.removeprefix("pip-").removesuffix("-py3-none-any.whl")
    source = Path(ensurepip.__file__)
    updated, count = re.subn(
        r'(?m)^_PIP_VERSION = "[^"]+"$',
        f'_PIP_VERSION = "{version}"',
        source.read_text(),
    )
    if count != 1:
        raise RuntimeError(f"Unrecognized ensurepip version declaration in {source}")
    bundled = source.parent / "_bundled"
    shutil.copyfile(wheel, bundled / wheel.name)
    source.write_text(updated)
    for old_wheel in bundled.glob("pip-*.whl"):
        if old_wheel.name != wheel.name:
            old_wheel.unlink()
    print(f"ensurepip now bundles pip {version}")


if __name__ == "__main__":
    main()
