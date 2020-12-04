#!/Library/installapplications/Python.framework/Versions/Current/bin/python3
# encoding: utf-8
#
# Copyright 2017-Present Erik Gomez.
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

from distutils.version import LooseVersion
from Foundation import NSLog
from SystemConfiguration import SCDynamicStoreCopyConsoleUser
import hashlib
import json
import optparse
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
import urllib.request, urllib.parse, urllib.error
sys.path.append('/Library/installapplications')
# PEP8 can really be annoying at times.
import gurl  # noqa


g_dry_run = False


def iaslog(text):
    try:
        NSLog('[InstallApplications] %s' % text)
    except Exception:
        print(text)
        pass


def getconsoleuser():
    cfuser = SCDynamicStoreCopyConsoleUser(None, None, None)
    return cfuser


def pkgregex(pkgpath):
    try:
        # capture everything after last / in the pkg filepath
        pkgname = re.compile(r"[^/]+$").search(pkgpath).group(0)
        return pkgname
    except AttributeError as IndexError:
        return pkgpath


def installpackage(packagepath):
    try:
        cmd = ['/usr/sbin/installer', '-verboseR', '-pkg', packagepath,
               '-target', '/']
        if g_dry_run:
            iaslog('Dry run installing package: %s' % packagepath)
            return 0
        proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        output, rcode = proc.communicate(), proc.returncode
        installlog = output[0].split('\n')
        # Filter all blank lines after the split.
        for line in [_f for _f in installlog if _f]:
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


def launchctl(*arg):
    # Use *arg to pass unlimited variables to command.
    cmd = arg
    run = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, err = run.communicate()
    return output


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


def runrootscript(pathname, donotwait):
    '''Runs script located at given pathname'''
    if g_dry_run:
        iaslog('Dry run executing root script: %s' % pathname)
        return True
    try:
        if donotwait:
            iaslog('Do not wait triggered')
            proc = subprocess.Popen(pathname)
            iaslog('Running Script: %s ' % pathname)
        else:
            iaslog('Running Script: %s ' % pathname)
            proc = subprocess.Popen(pathname, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            (out, err) = proc.communicate()
            iaslog('Output on stdout:')
            iaslog(out.decode('utf-8'))
            if err and proc.returncode == 0:
                iaslog('Output on stderr but ran successfully:')
                iaslog(err.decode('utf-8'))
            elif proc.returncode > 0:
                iaslog('Received non-zero exit code:')
                iaslog(err.decode('utf-8'))
                return False
    except OSError as err:
        iaslog('Failure running script:')
        iaslog(str(err.decode('utf-8')))
        return False
    return True


def runuserscript(iauserscriptpath):
    files = os.listdir(iauserscriptpath)
    for file in files:
        pathname = os.path.join(iauserscriptpath, file)
        if g_dry_run:
            iaslog('Dry run executing user script: %s' % pathname)
            os.remove(pathname)
            return True
        try:
            iaslog('Running Script: %s ' % pathname)
            proc = subprocess.Popen(pathname, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            (out, err) = proc.communicate()
            iaslog('Output on stdout:')
            iaslog(out.decode('utf-8'))
            if err and proc.returncode == 0:
                iaslog('Output on stderr but ran successfully:')
                iaslog(err.decode('utf-8'))
            elif proc.returncode > 0:
                iaslog('Received non-zero exit code:')
                iaslog(err.decode('utf-8'))
                return False
        except OSError as err:
            iaslog('Failure running script:')
            iaslog(str(err.decode('utf-8')))
            return False
        os.remove(pathname)
        return True
    else:
        iaslog('No user scripts found!')
        return False


def download_if_needed(item, stage, type, opts):
    # Check if the file exists and matches the expected hash.
    path = item['file']
    name = item['name']
    hash = item['hash']
    itemurl = item['url']
    while not (os.path.isfile(path) and hash == gethash(path)):
        # Check if additional headers are being passed and add
        # them to the dictionary.
        if opts.headers:
            item.update({'additional_headers':
                         {'Authorization': opts.headers}})
        # Check if we need to follow redirects.
        if opts.follow_redirects:
            item.update({'follow_redirects': True})
        # Download the file once:
        iaslog('Starting download: %s' % urllib.parse.unquote(itemurl))
        downloadfile(item)
        # Wait half a second to process
        time.sleep(0.5)
        # Check the files hash and redownload until it's
        # correct. Bail after three times and log event.
        failsleft = 3
        while not hash == gethash(path):
            iaslog('Hash failed for %s - received: %s expected'
                   ': %s' % (name, gethash(path), hash))
            downloadfile(item)
            failsleft -= 1
            if failsleft == 0:
                iaslog('Hash retry failed for %s: exiting!' % name)
                cleanup(1)
        # Time to install.
        iaslog('Hash validated - received: %s expected: %s' % (
               gethash(path), hash))
        # Fix script permissions.
        if os.path.splitext(path)[1] != ".pkg":
            os.chmod(path, 0o755)
        if type == 'userscript':
            os.chmod(path, 0o777)


def touch(path):
    try:
        touchfile = ['/usr/bin/touch', path]
        proc = subprocess.Popen(touchfile, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        touchfileoutput, err = proc.communicate()
        os.chmod(path, 0o777)
        return touchfileoutput
    except Exception:
        return None


def cleanup(exit_code):
    # Attempt to remove the LaunchDaemon
    iaslog('Attempting to remove LaunchDaemon: %s' % ialdpath)
    try:
        os.remove(ialdpath)
    except:  # noqa
        pass

    # Attempt to remove the LaunchAgent
    iaslog('Attempting to remove LaunchAgent: %s' % ialapath)
    try:
        os.remove(ialapath)
    except:  # noqa
        pass

    # Attempt to remove the launchagent from the user's list
    iaslog('Targeting user id for LaunchAgent removal: %s' % userid)
    iaslog('Attempting to remove LaunchAgent: %s' % laidentifier)
    launchctl('/bin/launchctl', 'asuser', userid,
              '/bin/launchctl', 'remove', laidentifier)

    # Trigger a delayed reboot of 5 seconds
    if reboot:
        iaslog('Triggering reboot')
        rebootcmd = [
            '/usr/bin/osascript',
            '-e',
            'delay 5',
            '-e',
            'tell application "System Events" to restart'
        ]
        try:
            subprocess.Popen(rebootcmd, preexec_fn=os.setpgrp)
        except:  # noqa
            pass

    # Attempt to kill InstallApplications' path
    iaslog('Attempting to remove InstallApplications directory: %s' % iapath)
    try:
        shutil.rmtree(iapath)
    except:  # noqa
        pass

    iaslog('Attempting to remove LaunchDaemon: %s' % ldidentifier)
    launchctl('/bin/launchctl', 'remove', ldidentifier)
    iaslog('Cleanup done. Exiting.')
    sys.exit(exit_code)


def main():
    # Options
    usage = '%prog [options]'
    o = optparse.OptionParser(usage=usage)
    o.add_option('--jsonurl', default=None,
                 help=('Required: URL to json file.'))
    o.add_option('--dry-run', default=False,
                 help=('Optional: Dry run (for testing).'),
                 action='store_true')
    o.add_option('--follow-redirects', default=False,
                 help=('Optional: Follow HTTP redirects.'),
                 action='store_true')
    o.add_option('--headers', default=None,
                 help=('Optional: Auth headers'))
    o.add_option('--iapath', default='/Library/installapplications',
                 help=('Optional: Specify InstallApplications package path.'))
    o.add_option('--laidentifier', default='com.erikng.installapplications',
                 help=('Optional: Specify LaunchAgent identifier.'))
    o.add_option('--ldidentifier', default='com.erikng.installapplications',
                 help=('Optional: Specify LaunchDaemon identifier.'))
    o.add_option('--reboot', default=False,
                 help=('Optional: Trigger a reboot.'),
                 action='store_true')
    o.add_option('--skip-validation', default=False,
                 help=('Optional: Skip bootstrap.json validation.'),
                 action='store_true')
    o.add_option('--userscript', default=None,
                 help=('Optional: Trigger a user script run.'),
                 action='store_true')

    opts, args = o.parse_args()

    # Dry run that doesn't actually run or install anything.
    if opts.dry_run:
        global g_dry_run
        g_dry_run = True

    # Check for root and json url.
    if opts.jsonurl:
        jsonurl = opts.jsonurl
        if not g_dry_run and (os.getuid() != 0):
            print('InstallApplications requires root!')
            sys.exit(1)
    else:
        if opts.userscript:
            pass
        else:
            iaslog('No JSON URL specified!')
            sys.exit(1)

    # Begin logging events
    iaslog('Beginning InstallApplications run')

    # installapplications variables
    global iapath
    iapath = opts.iapath
    iauserscriptpath = os.path.join(iapath, 'userscripts')
    iatmppath = '/var/tmp/installapplications'
    ialogpath = '/var/log/installapplications'
    iaslog('InstallApplications path: %s' % iapath)
    global ldidentifier
    ldidentifier = opts.ldidentifier
    ldidentifierplist = opts.ldidentifier + '.plist'
    global ialdpath
    ialdpath = os.path.join('/Library/LaunchDaemons', ldidentifierplist)
    iaslog('InstallApplications LaunchDaemon path: %s' % ialdpath)
    global laidentifier
    laidentifier = opts.laidentifier
    laidentifierplist = opts.laidentifier + '.plist'
    global ialapath
    ialapath = os.path.join('/Library/LaunchAgents', laidentifierplist)
    iaslog('InstallApplications LaunchAgent path: %s' % ialapath)

    global userid
    userid = str(getconsoleuser()[1])
    global reboot
    reboot = opts.reboot

    # hardcoded json fileurl path
    jsonpath = os.path.join(iapath, 'bootstrap.json')
    iaslog('InstallApplications json path: %s' % jsonpath)

    # User script touch path
    userscripttouchpath = '/var/tmp/installapplications/.userscript'

    if opts.userscript:
        iaslog('Running in userscript mode')
        uscript = runuserscript(iauserscriptpath)
        if uscript:
            os.remove(userscripttouchpath)
            sys.exit(0)
        else:
            iaslog('Failed to run user script!')
            os.remove(userscripttouchpath)
            sys.exit(1)
    else:
        # Ensure the log path is writable by all before launchagent tries to do anything
        if os.path.isdir(ialogpath):
            os.chmod(ialogpath, 0o777)

    # Ensure the directories exist
    if not os.path.isdir(iauserscriptpath):
        for path in [iauserscriptpath, iatmppath]:
            if not os.path.isdir(path):
                os.makedirs(path)
                os.chmod(path, 0o777)

    # Make the temporary folder
    try:
        os.makedirs(iapath)
    except Exception:
        pass

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

    # Check if we need to follow redirects.
    if opts.follow_redirects:
        item.update({'follow_redirects': True})

    # Delete the bootstrap file if it exists, to ensure it's up to date.
    if not opts.skip_validation:
        if os.path.isfile(jsonpath):
            iaslog('Removing and redownloading bootstrap.json')
            os.remove(jsonpath)

    # If the file doesn't exist, grab it and wait half a second to save.
    while not os.path.isfile(jsonpath):
        iaslog('Starting download: %s' % urllib.parse.unquote(
            json_data['url']))
        downloadfile(json_data)
        time.sleep(0.5)

    # Load up file to grab all the items.
    iajson = json.loads(open(jsonpath).read())

    # Set the stages
    stages = ['preflight', 'setupassistant', 'userland']

    # Process all stages
    for stage in stages:
        iaslog('Beginning %s' % stage)
        if stage == 'preflight':
            # Ensure we actually have a preflight key in the json
            try:
                iajson['preflight']
            except KeyError:
                iaslog('No preflight stage found: skipping.')
                continue
        # Loop through the items and download/install/run them.
        for item in iajson[stage]:
            # Set the filepath, name and type.
            try:
                path = item['file']
                name = item['name']
                type = item['type']
            except KeyError as e:
                iaslog('Invalid item %s: %s' % (repr(item), str(e)))
                continue
            iaslog('%s processing %s %s at %s' % (stage, type, name, path))

            # On userland stage, we want to wait until we are actually
            # in the user's session.
            if stage == 'userland':
                if len(iajson['userland']) > 0:
                    while (getconsoleuser()[0] is None
                           or getconsoleuser()[0] == 'loginwindow'
                           or getconsoleuser()[0] == '_mbsetupuser'):
                        iaslog('Detected SetupAssistant in userland '
                               'stage - delaying install until user '
                               'session.')
                        time.sleep(1)

            if type == 'package':
                packageid = item['packageid']
                version = item['version']
                try:
                    pkg_required = item['required']
                except KeyError:
                    pkg_required = False
                # Compare version of package with installed version and ensure
                # pkg is not a required install
                if LooseVersion(checkreceipt(packageid)) >= LooseVersion(
                        version) and not pkg_required:
                    iaslog('Skipping %s - already installed.' % name)
                else:
                    # Download the package if it isn't already on disk.
                    download_if_needed(item, stage, type, opts)

                    iaslog('Installing %s from %s' % (name, path))
                    # Install the package
                    installpackage(item['file'])
            elif type == 'rootscript':
                if 'url' in item:
                    download_if_needed(item, stage, type, opts)
                iaslog('Starting root script: %s' % path)
                try:
                    donotwait = item['donotwait']
                except KeyError as e:
                    donotwait = False
                if stage == 'preflight':
                    preflightrun = runrootscript(path, donotwait)
                    if preflightrun:
                        iaslog('Preflight passed all checks. Skipping run.')
                        userid = str(getconsoleuser()[1])
                        cleanup(0)
                    else:
                        iaslog('Preflight did not pass all checks. '
                               'Continuing run.')
                        continue

                runrootscript(path, donotwait)
            elif type == 'userscript':
                if 'url' in item:
                    download_if_needed(item, stage, type, opts)
                if stage == 'setupassistant':
                    iaslog('Detected setupassistant and user script. '
                           'User scripts cannot work in setupassistant stage! '
                           'Removing %s' % path)
                    os.remove(path)
                    continue
                iaslog('Triggering LaunchAgent for user script: %s' % path)
                touch(userscripttouchpath)
                while os.path.isfile(userscripttouchpath):
                    iaslog('Waiting for user script to complete: %s' % path)
                    time.sleep(0.5)

    # Cleanup and send good exit status
    cleanup(0)


if __name__ == '__main__':
    main()
