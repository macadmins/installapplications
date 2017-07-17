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
sys.path.append('/usr/local/installapplications')
# PEP8 can really be annoying at times.
import gurl  # noqa


def deplog(text):
    depnotify = '/private/var/tmp/depnotify.log'
    with open(depnotify, 'a+') as log:
        log.write(text + '\n')


def iaslog(text):
    print(text)
    iaslog = '/private/var/log/installapplications.log'
    with open(iaslog, 'a+') as log:
        log.write(text + '\n')


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
                        iaslog('Percent complete: %s ' % (percent_complete))
                elif connection.bytesReceived != bytes_received:
                    bytes_received = connection.bytesReceived
                    iaslog('Bytes received: %s ' % (bytes_received))

    except (KeyboardInterrupt, SystemExit):
        # safely kill the connection then fall through
        connection.cancel()
    except Exception:  # too general, I know
        # Let us out! ... Safely! Unexpectedly quit dialogs are annoying ...
        connection.cancel()
        # Re-raise the error
        raise

    if connection.error is not None:
        iaslog('Error: %s %s ' % (str(connection.error.code()),
                                  str(connection.error.localizedDescription()))
               )
        if connection.SSLerror:
            iaslog('SSL error: %s ' % (str(connection.SSLerror)))
    if connection.response is not None:
        iaslog('Status: %s ' % (str(connection.status)))
        iaslog('Headers: %s ' % (str(connection.headers)))
    if connection.redirection != []:
        iaslog('Redirection: %s ' % (str(connection.redirection)))


def main():
    # Options
    usage = '%prog [options]'
    o = optparse.OptionParser(usage=usage)
    o.add_option('--depnotify', default=None,
                 help=('Optional: Write our package info to DEPNotify'),
                 action='store_true')
    o.add_option('--headers', help=('Optional: Auth headers'))
    o.add_option('--jsonurl', help=('Required: URL to json file.'))
    o.add_option('--reboot', default=None,
                 help=('Optional: Trigger a reboot.'), action='store_true')

    opts, args = o.parse_args()

    # Check for root and json url.
    if opts.jsonurl:
        jsonurl = opts.jsonurl
        if os.getuid() != 0:
            print 'InstallApplications requires root!'
            sys.exit(1)
    else:
        iaslog('No URL specified!')
        sys.exit(1)

    # Begin logging events
    iaslog('Beginning InstallApplications run')

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

    # Grab auth headers if they exist and update the json_data dict.
    if opts.headers:
        headers = {'Authorization': opts.headers}
        json_data.update({'additional_headers': headers})

    # Make the temporary folder
    try:
        os.makedirs(iapath)
    except Exception:
        pass

    # If the file doesn't exist, grab it and wait half a second to save.
    while not os.path.isfile(jsonpath):
        iaslog('Downloading %s' % (json_data))
        downloadfile(json_data)
        time.sleep(0.5)

    # Load up file to grab all the packages.
    iajson = json.loads(open(jsonpath).read())

    # Set the stages
    stages = ['prestage', 'stage1', 'stage2']

    # Get the number of packages for DEPNotify
    if opts.depnotify:
        numberofpackages = 0
        for stage in stages:
            numberofpackages += int(len(iajson[stage]))
        deplog('Command: Determinate: %d' % (numberofpackages))

    # Process all stages
    for stage in stages:
        # On Stage 1, we want to wait until we are actually in the user's
        # session. Stage 1 is ideally used for installing files you need
        # immediately.
        iaslog('Beginning %s' % (stage))
        if stage == 'stage1':
            if len(iajson['stage1']) > 0:
                while (getconsoleuser() is None
                       or getconsoleuser() == u'loginwindow'
                       or getconsoleuser() == u'_mbsetupuser'):
                    iaslog('Detected Stage 1 - waiting for user session.')
                    time.sleep(1)

        # Loop through the packages and download/install them.
        for package in iajson[stage]:
            # Set the filepath
            path = x['file']
            # Check if the file already exists and matches the expected hash.
            while not (os.path.isfile(path) and package['hash'] == gethash(path
                                                                           )):
                # Check if additional headers are being passed and add them
                # to the dictionary.
                if opts.headers:
                    package.update({'additional_headers': headers})
                # Download the file once:
                iaslog('Downloading %s' % (package['url']))
                downloadfile(package)
                # Wait half a second to process
                time.sleep(0.5)
                # Check the files hash and redownload until it's correct.
                # Bail after three times and log event.
                failsleft = 3
                while not package['hash'] == gethash(path):
                    iaslog('Hash failed - received: %s expected: %s' % (
                        gethash(path), package['hash']))
                    downloadfile(package)
                    failsleft -= 1
                    if failsleft == 0:
                        iaslog('Hash retry failed: exiting!')
                        sys.exit(1)
                # Time to install.
                iaslog('Hash validated - received: %s expected: %s' % (
                    gethash(path), package['hash']))
                iaslog('Installing %s from %s' % (package['name'],
                                                  package['file']))
                if opts.depnotify:
                    deplog('Status: Installing: %s' % (package['name']))
                    deplog('Command: Notification: %s' % (package['name']))
                installpackage(package['file'])

    # Kill the launchdaemon
    try:
        os.remove(ialdpath)
    except:  # noqa
        pass

    # Kill the bootstrap path.
    try:
        shutil.rmtree('/private/tmp/installapplications')
    except:  # noqa
        pass

    # Trigger a reboot
    if opts.reboot:
        subprocess.call(['/sbin/shutdown', '-r', 'now'])


if __name__ == '__main__':
    main()
