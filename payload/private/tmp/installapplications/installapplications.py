#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009-2017 Erik Gomez.
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# InstallApplications
# This script uses munki's gurl.py to download the initial json and
# subsequent packages securely, and then install them. This allows your DEP
# bootstrap to be completely dynamic and easily updateable.
# downloadfile function taken from:
# https://gist.github.com/gregneagle/1816b650df8e3fbeb18f
# gurl.py and gethash function taken from:
# https://github.com/munki/munki
# Notice a pattern?

from SystemConfiguration import SCDynamicStoreCopyConsoleUser
import hashlib
import json
import optparse
import os
import shutil
import subprocess
import sys
import time
sys.path.append('/private/tmp/installapplications')
# PEP8 can really be annoying at times.
import gurl  # noqa


def getconsoleuser():
    cfuser = SCDynamicStoreCopyConsoleUser(None, None, None)
    return cfuser[0]


def installpackage(packagepath):
    try:
        cmd = ['/usr/sbin/installer', '-verboseR', '-pkg', packagepath,
               '-target', '/']
        proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        output = proc.communicate()
        return output
    except Exception:
        pass


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


def downloadfile(options):
    connection = gurl.Gurl.alloc().initWithOptions_(options)
    percent_complete = -1
    bytes_received = 0
    connection.start()
    try:
        while not connection.isDone():
            if connection.destination_path:
                # only print progress info if we are writing to a file
                if connection.percentComplete != -1:
                    if connection.percentComplete != percent_complete:
                        percent_complete = connection.percentComplete
                        print 'Percent complete: %s' % percent_complete
                elif connection.bytesReceived != bytes_received:
                    bytes_received = connection.bytesReceived
                    print 'Bytes received: %s' % bytes_received

    except (KeyboardInterrupt, SystemExit):
        # safely kill the connection then fall through
        connection.cancel()
    except Exception:  # too general, I know
        # Let us out! ... Safely! Unexpectedly quit dialogs are annoying ...
        connection.cancel()
        # Re-raise the error
        raise

    if connection.error is not None:
        print 'Error:', (connection.error.code(),
                         connection.error.localizedDescription())
        if connection.SSLerror:
            print 'SSL error:', connection.SSLerror
    if connection.response is not None:
        print 'Status:', connection.status
        print 'Headers:', connection.headers
    if connection.redirection != []:
        print 'Redirection:', connection.redirection


def main():
    # Options
    usage = '%prog [options]'
    o = optparse.OptionParser(usage=usage)
    o.add_option('--jsonurl',
                 help=('Required: URL to json file.'))

    opts, args = o.parse_args()

    # Check for root and json url.
    if opts.jsonurl:
        jsonurl = opts.jsonurl
        if os.getuid() != 0:
            print 'InstallApplications requires root!'
            sys.exit(1)
    else:
        print 'No URL specified!'
        sys.exit(1)

    # installapplications variables
    iapath = '/private/tmp/installapplications'
    ialdpath = '/Library/LaunchDaemons/com.erikng.installapplications.plist'

    # hardcoded json fileurl path
    jsonpath = '/private/tmp/installapplications/bootstrap.json'

    # json data for gurl download
    json_data = {
            'url': jsonurl,
            'file': jsonpath,
        }

    # Make the temporary folder
    try:
        os.makedirs(iapath)
    except Exception:
        pass

    # If the file doesn't exist, grab it and wait half a second to save.
    while not os.path.isfile(jsonpath):
        downloadfile(json_data)
        time.sleep(0.5)

    # Load up file to grab all the packages.
    iajson = json.loads(open(jsonpath).read())

    # Process both stages
    stages = ['stage1', 'stage2']
    for stage in stages:
        # Loop through the packages and download them.
        for x in iajson[stage]:
            # Set the filepath
            path = x['file']
            # Check if the file already exists and matches the expected hash.
            while not (os.path.isfile(path) and x['hash'] == gethash(path)):
                # Download the file once:
                downloadfile(x)
                # Wait half a second to process
                time.sleep(0.5)
                # Check the files hash and redownload until it's correct.
                while not x['hash'] == gethash(path):
                    downloadfile(x)

        # Now that we have validated the packages, let's get the list and
        # ensure they are in the order we expect.
        packagelist = []
        for file in os.listdir(iapath):
            if file.endswith('.pkg'):
                packagelist.append(os.path.join(iapath, file))

        packagelist = sorted(packagelist)

        # On Stage 1, we want to wait until we are actually in the user's
        # session. Stage 1 is ideally used for installing files you need
        # immediately.
        if stage == 'stage1':
            while (getconsoleuser() is None
                   or getconsoleuser() == u"loginwindow"
                   or getconsoleuser() == u"_mbsetupuser"):
                time.sleep(1)

        # Time to install.
        for packagepath in packagelist:
            print("Installing %s" % (packagepath))
            installpackage(packagepath)
            os.remove(packagepath)

    # Kill the launchdaemon
    os.remove(ialdpath)

    # Kill the dep bootstrap path.
    shutil.rmtree(iapath)


if __name__ == '__main__':
    main()
