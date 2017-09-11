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

from Foundation import NSLog
from SystemConfiguration import SCDynamicStoreCopyConsoleUser
import hashlib
import json
import optparse
import os
import re
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
    NSLog('[InstallApplications] ' + text)
    iaslog = '/private/var/log/installapplications.log'
    formatstr = '%b %d %Y %H:%M:%S %z: '
    with open(iaslog, 'a+') as log:
        log.write(time.strftime(formatstr) + text + '\n')


def getconsoleuser():
    cfuser = SCDynamicStoreCopyConsoleUser(None, None, None)
    return cfuser[0]


def pkgregex(pkgpath):
    try:
        # capture everything after last / in the pkg filepath
        pkgname = re.compile(r"[^/]+$").search(pkgpath).group(0)
        return pkgname
    except AttributeError, IndexError:
        return packagepath


def installpackage(packagepath):
    try:
        cmd = ['/usr/sbin/installer', '-verboseR', '-pkg', packagepath,
               '-target', '/']
        proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        output, rcode = proc.communicate(), proc.returncode
        installlog = output[0].split('\n')
        # Filter all blank lines after the split.
        for line in filter(None, installlog):
            # Replace any instances of % with a space and any elipsis with
            # a blank line since NSLog can't handle these kinds of characters.
            # Hopefully this is the only bad characters we will ever run into.
            logline = line.replace('%', ' ').replace('\xe2\x80\xa6', '')
            iaslog(logline)
        return rcode
    except Exception:
        pass


def checkreceipt(packageid):
    try:
        cmd = ['/usr/sbin/pkgutil', '--pkg-info-plist', packageid]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output = proc.communicate()
        receiptout = output[0]
        if receiptout:
            plist = plistlib.readPlistFromString(receiptout)
            version = plist['pkg-version']
        else:
            version = '0.0.0.0.0'
        return version
    except Exception:
        version = '0.0.0.0.0'
        return version


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
        filename = options['name']
    except KeyError:
        iaslog('No \'name\' key defined in json for %s' %
               pkgregex(options['file']))
        sys.exit(1)

    try:
        while not connection.isDone():
            if connection.destination_path:
                # only print progress info if we are writing to a file
                if connection.percentComplete != -1:
                    if connection.percentComplete != percent_complete:
                        percent_complete = connection.percentComplete
                        iaslog('Downloading %s - Percent complete: %s ' % (
                               filename, percent_complete))
                elif connection.bytesReceived != bytes_received:
                    bytes_received = connection.bytesReceived
                    iaslog('Downloading %s - Bytes received: %s ' % (
                           filename, bytes_received))

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


def vararg_callback(option, opt_str, value, parser):
    # https://docs.python.org/3/library/optparse.html#callback-example-6-
    # variable-arguments
    assert value is None
    value = []

    def floatable(str):
        try:
            float(str)
            return True
        except ValueError:
            return False

    for arg in parser.rargs:
        # stop on --foo like options
        if arg[:2] == "--" and len(arg) > 2:
            break
        value.append(arg)

    del parser.rargs[:len(value)]
    setattr(parser.values, option.dest, value)


def main():
    # Options
    usage = '%prog [options]'
    o = optparse.OptionParser(usage=usage)
    o.add_option('--depnotify', default=None,
                 dest="depnotify",
                 action="callback",
                 callback=vararg_callback,
                 help=('Optional: Utilize DEPNotify and pass options to it.'))
    o.add_option('--headers', help=('Optional: Auth headers'))
    o.add_option('--jsonurl', help=('Required: URL to json file.'))
    o.add_option('--reboot', default=None,
                 help=('Optional: Trigger a reboot.'), action='store_true')

    opts, args = o.parse_args()

    # DEPNotify trigger commands that need to happen at the end of a run
    deptriggers = ['Command: Quit', 'Command: Restart', 'Command: Logout',
                   'DEPNotifyPath']

    # Look for all the DEPNotify options but skip the ones that are usual
    # done after a full run.
    if opts.depnotify:
        for varg in opts.depnotify:
            notification = str(varg)
            if any(x in notification for x in deptriggers):
                continue
            else:
                deplog(notification)

    # Check for root and json url.
    if opts.jsonurl:
        jsonurl = opts.jsonurl
        if os.getuid() != 0:
            print 'InstallApplications requires root!'
            sys.exit(1)
    else:
        iaslog('No JSON URL specified!')
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
            'name': 'Bootstrap.json'
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
        iaslog('Starting download: %s' % (json_data['url']))
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
            if stage == 'prestage':
                iaslog('Skipping DEPNotify package countdue to prestage.')
            else:
                numberofpackages += int(len(iajson[stage]))
        # Mulitply by two for download and installation status messages
        deplog('Command: Determinate: %d' % (numberofpackages*2))

    # Process all stages
    for stage in stages:
        iaslog('Beginning %s' % (stage))
        # Loop through the packages and download/install them.
        for package in iajson[stage]:
            # Set the filepath and hash
            path = package['file']
            hash = package['hash']
            name = package['name']
            packageid = package['packageid']
            version = package['version']
            # Compare version of pacakge with installed version
            if LooseVersion(checkreceipt(packageid)) >= LooseVersion(version):
                iaslog('Skipping %s - already installed.' % (name))
            else:
                # Check if the file exists and matches the expected hash.
                while not (os.path.isfile(path) and hash == gethash(path)):
                    # Check if additional headers are being passed and add them
                    # to the dictionary.
                    if opts.headers:
                        package.update({'additional_headers': headers})
                    # Download the file once:
                    iaslog('Starting download: %s' % (package['url']))
                    if opts.depnotify:
                        if stage == 'prestage':
                            iaslog(
                                'Skipping DEPNotify notification due to \
                                prestage.')
                        else:
                            deplog('Status: Downloading %s' % (name))
                    downloadfile(package)
                    # Wait half a second to process
                    time.sleep(0.5)
                    # Check the files hash and redownload until it's correct.
                    # Bail after three times and log event.
                    failsleft = 3
                    while not hash == gethash(path):
                        iaslog('Hash failed for %s - received: %s expected: \
                               %s' % (name, gethash(path), hash))
                        downloadfile(package)
                        failsleft -= 1
                        if failsleft == 0:
                            iaslog('Hash retry failed for %s: exiting!' % name)
                            sys.exit(1)
                    # Time to install.
                    iaslog('Hash validated - received: %s expected: %s' % (
                           gethash(path), hash))
                    # On Stage 1, we want to wait until we are actually in the
                    # user's session. Stage 1 is ideally used for installing
                    # files you need immediately.
                    if stage == 'stage1':
                        if len(iajson['stage1']) > 0:
                            while (getconsoleuser() is None
                                   or getconsoleuser() == u'loginwindow'
                                   or getconsoleuser() == u'_mbsetupuser'):
                                iaslog('Detected Stage 1 - delaying install \
                                       until user session.')
                                time.sleep(1)
                        # Open DEPNotify for the admin if they pass condition.
                        if opts.depnotify:
                            for varg in opts.depnotify:
                                notification = str(varg)
                                if 'DEPNotifyPath:' in notification:
                                    depnotifypath = notification.split(' ')[-1]
                                    subprocess.call(['/usr/bin/open',
                                                     depnotifypath])
                                else:
                                    continue
                    iaslog('Installing %s from %s' % (name, path))
                    if opts.depnotify:
                        if stage == 'prestage':
                            iaslog(
                                'Skipping DEPNotify notification due to \
                                prestage.')
                        else:
                            deplog('Status: Installing: %s' % (name))
                            deplog('Command: Notification: %s' % (name))
                    # We now check the install return code status since some
                    # packages like to delete themselves after they run. Why
                    # would you do this developers?
                    # Palo Alto Networks / GlobalProtect
                    installerstatus = installpackage(package['file'])
                    if installerstatus == 0:
                        break

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

    # Trigger the final DEPNotify events
    if opts.depnotify:
        for varg in opts.depnotify:
            notification = str(varg)
            if any(x in notification for x in deptriggers):
                deplog(notification)
            else:
                iaslog(
                    'Skipping DEPNotify notification event due to completion.')

    # Trigger a reboot
    if opts.reboot:
        subprocess.call(['/sbin/shutdown', '-r', 'now'])


if __name__ == '__main__':
    main()
