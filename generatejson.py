#!/usr/bin/python
# -*- coding: utf-8 -*-

# Generate Json file for installapplications
# Usage: python generatejson.py --rootdir /path/to/rootdir
#
# --rootdir path is the directory that contains each stage's pkgs directory
# As of InstallApplications 7/18/17, the directories must be named (lowercase):
#   'setupassistant', and 'userland'
#
# The generated Json will be saved in the root directory
# Future plan for this tool is to add AWS S3 integration for auto-upload

import hashlib
import json
import optparse
import os
import sys
import subprocess
import tempfile
from xml.dom import minidom


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


def getpkginfopath(filename):
    '''Extracts the package BOM with xar'''
    cmd = ['/usr/bin/xar', '-tf', filename]
    proc = subprocess.Popen(cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (bom, err) = proc.communicate()
    bom = bom.strip().split('\n')
    if proc.returncode == 0:
        for entry in bom:
            if entry.startswith('PackageInfo'):
                return entry
            elif entry.endswith('.pkg/PackageInfo'):
                return entry
    else:
        print "Error: %s while extracting BOM for %s" % (err, filename)


def extractpkginfo(filename):
    '''Takes input of a file path and returns a file path to the
    extracted PackageInfo file.'''
    cwd = os.getcwd()

    if not os.path.isfile(filename):
        return
    else:
        tmpFolder = tempfile.mkdtemp()
        os.chdir(tmpFolder)
        # need to get path from BOM
        pkgInfoPath = getpkginfopath(filename)

        extractedPkgInfoPath = os.path.join(tmpFolder, pkgInfoPath)
        cmd = ['/usr/bin/xar', '-xf', filename, pkgInfoPath]
        proc = subprocess.Popen(cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        out, err = proc.communicate()
        os.chdir(cwd)
        return extractedPkgInfoPath


def getpkginfo(filename):
    '''Takes input of a file path and returns strings of the
    package identifier and version from PackageInfo.'''
    if not os.path.isfile(filename):
        return "", ""

    else:
        pkgInfoPath = extractpkginfo(filename)
        dom = minidom.parse(pkgInfoPath)
        pkgRefs = dom.getElementsByTagName('pkg-info')
        for ref in pkgRefs:
            pkgId = ref.attributes['identifier'].value.encode('UTF-8')
            pkgVersion = ref.attributes['version'].value.encode('UTF-8')
            return pkgId, pkgVersion


def main():
    usage = '%prog --rootdir <filepath>'
    op = optparse.OptionParser(usage=usage)
    op.add_option('--rootdir', help=(
        'Required: Root directory path for InstallApplications stages'))
    op.add_option('--outputdir', default=None, help=('Optional: Output \
                  directory to save in. Default saves in the rootdir'))
    op.add_option('--base-url', default=None, action='store',
                  help=('Base URL to where root dir is hosted'))
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
        for file in sorted(files):
            fileext = os.path.splitext(file)[1]
            if fileext not in ('.pkg', '.py', '.sh', '.rb', '.php'):
                continue
            filepath = os.path.join(subdir, file)
            filename = os.path.basename(filepath)
            filehash = gethash(filepath)
            filestage = os.path.basename(os.path.abspath(
                        os.path.join(filepath, os.pardir)))
            if opts.base_url:
                fileurl = '%s/%s/%s' % (opts.base_url, filestage, filename)
            else:
                fileurl = ''
            filejson = {'file':
                        '/Library/Application Support/installapplications/%s' % filename,
                        'url': fileurl, 'hash': str(filehash),
                        'name': filename}
            if fileext == '.pkg':
                (pkgid, pkgversion) = getpkginfo(filepath)
                filejson['type'] = 'package'
                filejson['packageid'] = pkgid
                filejson['version'] = pkgversion
                stages[filestage].append(filejson)
            else:
                filejson['type'] = 'rootscript'
                stages[filestage].append(filejson)

        # make sure that we have a preflight key
        try:
            stages['preflight']
        except KeyError:
            stages['preflight'] = []

    # Saving the file back in the root dir
    if opts.outputdir:
        savepath = os.path.join(opts.outputdir, 'bootstrap.json')
    else:
        savepath = os.path.join(rootdir, 'bootstrap.json')

    try:
        with open(savepath, 'w') as outfile:
            json.dump(stages, outfile, sort_keys=True, indent=2)
    except IOError:
        print '[Error] Not a valid directory: %s' % savepath
        sys.exit(1)

    print 'Json saved to %s' % savepath


if __name__ == '__main__':
    main()
