#!/usr/bin/python
# -*- coding: utf-8 -*-

# Generate Json file for installapplications
# Usage: python generatejson.py --rootdir /path/to/rootdir
#
# --rootdir path is the directory that contains each stage's pkgs directory
# As of InstallApplications 5/13/17, the directories must be named (lowercase):
#   'prestage', 'stage1', and 'stage3'
#
# The generated Json will be saved in the root directory
# Future plan for this tool is to add AWS S3 integration for auto-upload

import hashlib
import json
import optparse
import os
import sys

# Hash function borrowed from InstallApplications.py, thanks Erik
def gethash(filename):
    hash_function = hashlib.sha256()
    if not os.path.isfile(filename):
        return 'NOT A FILE'

    fileref = open(filename, 'rb')
    while 1:
        chunk = fileref.read(2**16)
        if not chunk:
            break
        hash_function.update(chunk)
    fileref.close()
    return hash_function.hexdigest()

def main():
    usage = '%prog --rootdir <filepath>'
    op = optparse.OptionParser(usage=usage)
    op.add_option('--rootdir', help=(
        'Required: Root directory path for InstallApplications stages'))
    opts, args = op.parse_args()

    if opts.rootdir:
        rootdir = opts.rootdir
    else:
        op.print_help()
        sys.exit(1)

    # Traverse through root dir, find all stages and all pkgs to generate json
    stages = {}
    for subdir, dirs, files in os.walk(rootdir):
        for d in dirs:
            stages[str(d)] = []
        for file in files:
            if file.endswith('.pkg'):
                filepath = os.path.join(subdir, file)
                filename = os.path.basename(filepath)
                filehash = gethash(filepath)
                filestage = os.path.basename(os.path.abspath(
                            os.path.join(filepath, os.pardir)))
                filejson = {"file":
                            "/private/tmp/installapplications/%s" % filename,
                            "url": "", "hash:": str(filehash)}
                stages[filestage].append(filejson)

    # Saving the file back in the root dir
    savepath = os.path.join(rootdir, "bootstrap.json")
    with open(savepath, 'w') as outfile:
        json.dump(stages, outfile, sort_keys=True, indent=2)

    print "Json saved to %s" % savepath


if __name__ == '__main__':
    main()
