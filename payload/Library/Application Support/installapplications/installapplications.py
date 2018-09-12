#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009-2018 Erik Gomez.
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
# gurl.py, gethash function, and import_plugin (middleware) taken from:
# https://github.com/munki/munki
# Notice a pattern?

from distutils.version import LooseVersion
from Foundation import NSLog
from SystemConfiguration import SCDynamicStoreCopyConsoleUser
import gurl  # noqa
import hashlib
import imp
import json
import optparse
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
import urllib

g_dry_run = False
plugin = None
middleware = None


def deplog(text):
    depnotify = '/private/var/tmp/depnotify.log'
    with open(depnotify, 'a+') as log:
        log.write(text + '\n')


def iaslog(text):
    NSLog('[InstallApplications] ' + text)


def getconsoleuser():
    cfuser = SCDynamicStoreCopyConsoleUser(None, None, None)
    return cfuser


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
        if g_dry_run:
            iaslog('Dry run installing package: %s' % packagepath)
            return 0
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


def launchctl(*arg):
    # Use *arg to pass unlimited variables to command.
    cmd = arg
    run = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, err = run.communicate()
    return output


def downloadfile(options):
    # Allow middleware to modify options
    if middleware:
        iaslog('Processing options through middleware')
        # middleware module must have process_request_options function
        # and must return usable options
        options = middleware.process_request_options(options)
        iaslog('Options: %s' % options)
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
            iaslog('Running Script: %s ' % (str(pathname)))
        else:
            proc = subprocess.Popen(pathname, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            iaslog('Running Script: %s ' % (str(pathname)))
            (out, err) = proc.communicate()
            if err and proc.returncode == 0:
                iaslog('Output from %s on stderr but ran successfully: %s' %
                       (pathname, err))
            elif proc.returncode > 0:
                iaslog('Received non-zero exit code: ' + str(err))
                return False
    except OSError as err:
        iaslog('Failure running script: ' + str(err))
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
            proc = subprocess.Popen(pathname, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            iaslog('Running Script: %s ' % (str(pathname)))
            (out, err) = proc.communicate()
            if err and proc.returncode == 0:
                iaslog(
                    'Output from %s on stderr but ran successfully: %s' %
                    (pathname, err))
            elif proc.returncode > 0:
                iaslog('Failure running script: ' + str(err))
                return False
        except OSError as err:
            iaslog('Failure running script: ' + str(err))
            return False
        os.remove(pathname)
        return True
    else:
        iaslog('No user scripts found!')
        return False


def download_if_needed(item, stage, type, opts, depnotifystatus):
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
        # Download the file once:
        iaslog('Starting download: %s' % (urllib.unquote(itemurl.decode('utf8')
                                                         )))
        if opts.depnotify:
            if stage == 'setupassistant':
                iaslog('Skipping DEPNotify notification due to setupassistant.'
                       )
            else:
                if depnotifystatus:
                    deplog('Status: Downloading %s' % (name))
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
                sys.exit(1)
        # Time to install.
        iaslog('Hash validated - received: %s expected: %s' % (
               gethash(path), hash))
        # Fix script permissions.
        if os.path.splitext(path)[1] != ".pkg":
            os.chmod(path, 0755)
        if type is 'userscript':
            os.chmod(path, 0777)


def touch(path):
    try:
        touchfile = ['/usr/bin/touch', path]
        proc = subprocess.Popen(touchfile, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        touchfileoutput, err = proc.communicate()
        os.chmod(path, 0777)
        return touchfileoutput
    except Exception:
        return None


def cleanup(iapath, ialdpath, ldidentifier, ialapath, laidentifier, userid,
            reboot):
    # Attempt to remove the LaunchDaemon
    iaslog('Attempting to remove LaunchDaemon: ' + ialdpath)
    try:
        os.remove(ialdpath)
    except:  # noqa
        pass

    # Attempt to remove the LaunchAgent
    iaslog('Attempting to remove LaunchAgent: ' + ialapath)
    try:
        os.remove(ialapath)
    except:  # noqa
        pass

    # Attempt to remove the launchagent from the user's list
    iaslog('Targeting user id for LaunchAgent removal: ' + userid)
    iaslog('Attempting to remove LaunchAgent: ' + laidentifier)
    launchctl('/bin/launchctl', 'asuser', userid,
              '/bin/launchctl', 'remove', laidentifier)

    # Attempt to kill InstallApplications' path
    iaslog('Attempting to remove InstallApplications directory: ' + iapath)
    try:
        shutil.rmtree(iapath)
    except:  # noqa
        pass

    if not reboot:
        iaslog('Attempting to remove LaunchDaemon: ' + ldidentifier)
        launchctl('/bin/launchctl', 'remove', ldidentifier)
        iaslog('Cleanup done. Exiting.')
        sys.exit(0)


def import_plugin_middleware():
    # Thanks to authors of munkilib/fetch.py (middleware)
    '''Check installapplications folder for a python file that starts with
    plugin or middleware. If a plugin file exists and has a callable
    'process_item' attribute, the module is loaded under the 'plugin' name.
    If a middleware file exists and has a callable 'process_request_options'
    attribute, the module is loaded under the 'middleware' name'''
    plugin_req_function = 'process_item'
    middleware_req_function = 'process_request_options'
    ias_dir = os.path.abspath(os.path.dirname(__file__))
    for filename in os.listdir(ias_dir):
        if (filename.startswith('plugin')
                and os.path.splitext(filename)[1] == '.py'):
            name = os.path.splitext(filename)[0]
            filepath = os.path.join(ias_dir, filename)
            try:
                _tmp = imp.load_source(name, filepath)
                if hasattr(_tmp, plugin_req_function):
                    if callable(getattr(_tmp, plugin_req_function)):
                        iaslog('Loading plugin module %s' % filename)
                        globals()['plugin'] = _tmp
                        return
                    else:
                        iaslog('%s attribute in %s is not callable'
                               % (plugin_req_function, filepath))
                        iaslog('Ignoring %s' % filepath)
                else:
                    iaslog('%s does not have a %s function'
                           % (filepath, plugin_req_function))
                    iaslog('Ignoring %s' % filepath)
            except BaseException:
                iaslog(
                    'Ignoring %s because of error importing module' % filepath)
        elif (filename.startswith('middleware')
                and os.path.splitext(filename)[1] == '.py'):
            name = os.path.splitext(filename)[0]
            filepath = os.path.join(ias_dir, filename)
            try:
                _tmp = imp.load_source(name, filepath)
                if hasattr(_tmp, middleware_req_function):
                    if callable(getattr(_tmp, middleware_req_function)):
                        iaslog('Loading middleware module %s' % filename)
                        globals()['middleware'] = _tmp
                        return
                    else:
                        iaslog('%s attribute in %s is not callable'
                               % (middleware_req_function, filepath))
                        iaslog('Ignoring %s' % filepath)
                else:
                    iaslog('%s does not have a %s function'
                           % (filepath, middleware_req_function))
                    iaslog('Ignoring %s' % filepath)
            except BaseException:
                iaslog(
                    'Ignoring %s because of error importing module' % filepath)
    return


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
    o.add_option('--iapath',
                 default='/Library/Application Support/installapplications',
                 help=('Optional: Specify InstallApplications package path.'))
    o.add_option('--ldidentifier',
                 default='com.erikng.installapplications',
                 help=('Optional: Specify LaunchDaemon identifier.'))
    o.add_option('--laidentifier',
                 default='com.erikng.installapplications',
                 help=('Optional: Specify LaunchAgent identifier.'))
    o.add_option('--reboot', default=False,
                 help=('Optional: Trigger a reboot.'), action='store_true')
    o.add_option('--dry-run', help=('Optional: Dry run (for testing).'),
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
        globals()['g_dry_run'] = True

    # Check for root and json url.
    if opts.jsonurl:
        jsonurl = opts.jsonurl
        if not g_dry_run and (os.getuid() != 0):
            print 'InstallApplications requires root!'
            sys.exit(1)
    else:
        if opts.userscript:
            pass
        else:
            iaslog('Error: No JSON URL specified!')
            sys.exit(1)

    # Begin logging events
    iaslog('Beginning InstallApplications run')

    # installapplications variables
    iapath = opts.iapath
    iauserscriptpath = os.path.join(iapath, 'userscripts')
    iatmppath = '/var/tmp/installapplications'
    iaslog('InstallApplications path: ' + str(iapath))
    ldidentifier = opts.ldidentifier
    ldidentifierplist = opts.ldidentifier + '.plist'
    ialdpath = os.path.join('/Library/LaunchDaemons', ldidentifierplist)
    iaslog('InstallApplications LaunchDaemon path: ' + str(ialdpath))
    laidentifier = opts.laidentifier
    laidentifierplist = opts.laidentifier + '.plist'
    ialapath = os.path.join('/Library/LaunchAgents', laidentifierplist)
    iaslog('InstallApplications LaunchAgent path: ' + str(ialapath))
    depnotifystatus = True
    reboot = opts.reboot

    # hardcoded json fileurl path
    jsonpath = os.path.join(iapath, 'bootstrap.json')
    iaslog('InstallApplications json path: ' + str(jsonpath))

    # User script touch path
    userscripttouchpath = '/var/tmp/installapplications/.userscript'

    if opts.userscript:
        iaslog('Running in userscript mode')
        uscript = runuserscript(iauserscriptpath)
        if uscript:
            os.remove(userscripttouchpath)
            sys.exit(0)
        else:
            iaslog('Error: Failed to run script!')
            sys.exit(1)

    # Ensure the directories exist
    if not os.path.isdir(iauserscriptpath):
        for path in [iauserscriptpath, iatmppath]:
            if not os.path.isdir(path):
                os.makedirs(path)
                os.chmod(path, 0777)

    # DEPNotify trigger commands that need to happen at the end of a run
    deptriggers = ['Command: Quit', 'Command: Restart', 'Command: Logout',
                   'DEPNotifyPath', 'DEPNotifyArguments',
                   'DEPNotifySkipStatus']

    # Look for all the DEPNotify options but skip the ones that are usually
    # done after a full run.
    if opts.depnotify:
        for varg in opts.depnotify:
            notification = str(varg)
            if any(x in notification for x in deptriggers):
                if 'DEPNotifySkipStatus' in notification:
                    depnotifystatus = False
            else:
                iaslog('Sending %s to DEPNotify' % (str(notification)))
                deplog(notification)

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

    # Delete the bootstrap file if it exists, to ensure it's up to date.
    if not opts.skip_validation:
        if os.path.isfile(jsonpath):
            iaslog('Removing and redownloading bootstrap.json')
            os.remove(jsonpath)

    # If the file doesn't exist, grab it and wait half a second to save.
    while not os.path.isfile(jsonpath):
        iaslog('Starting download: %s' % (urllib.unquote(
            json_data['url']).decode('utf8')))
        downloadfile(json_data)
        time.sleep(0.5)

    # Load up file to grab all the items.
    iajson = json.loads(open(jsonpath).read())

    # Set the stages
    stages = ['preflight', 'setupassistant', 'userland']

    # Get the number of items for DEPNotify
    if opts.depnotify:
        numberofitems = 0
        for stage in stages:
            if stage == 'setupassistant':
                iaslog('Skipping DEPNotify item count due to setupassistant.')
            else:
                # catch if there is a missing stage. mostly for preflight.
                try:
                    numberofitems += int(len(iajson[stage]))
                except KeyError:
                    iaslog('Malformed JSON - missing %s stage key' % stage)
        # Mulitply by two for download and installation status messages
        if depnotifystatus:
            deplog('Command: Determinate: %d' % (numberofitems*2))

    # Process all stages
    for stage in stages:
        iaslog('Beginning %s' % (stage))
        if stage == 'preflight':
            # Ensure we actually have a preflight key in the json
            try:
                iajson['preflight']
            except KeyError:
                iaslog('No preflight stage found: skipping.')
                continue
        if stage == 'userland':
            # Open DEPNotify for the admin if they pass
            # condition.
            depnotifypath = None
            depnotifyarguments = None
            if opts.depnotify:
                for varg in opts.depnotify:
                    depnstr = str(varg)
                    if 'DEPNotifyPath:' in depnstr:
                        depnotifypath = depnstr.split(' ', 1)[-1]
                    if 'DEPNotifyArguments:' in depnstr:
                        depnotifyarguments = depnstr.split(' ', 1)[-1]
            if depnotifypath:
                while (getconsoleuser()[0] is None
                       or getconsoleuser()[0] == u'loginwindow'
                       or getconsoleuser()[0] == u'_mbsetupuser'):
                    iaslog('Detected SetupAssistant in userland stage - '
                           'delaying DEPNotify launch until user session.')
                    time.sleep(1)
                iaslog('Creating DEPNotify Launcher')
                depnotifyscriptpath = os.path.join(
                    iauserscriptpath,
                    'depnotifylauncher.py')
                if depnotifyarguments:
                    if '-munki' in depnotifyarguments:
                        # Touch Munki Logs if they do not exist so DEPNotify
                        # can show them.
                        mlogpath = '/Library/Managed Installs/Logs'
                        mlogfile = os.path.join(mlogpath,
                                                'ManagedSoftwareUpdate.log')
                        if not os.path.isdir(mlogpath):
                            os.makedirs(mlogpath, 0755)
                        if not os.path.isfile(mlogfile):
                            touch(mlogfile)
                    if len(depnotifyarguments) >= 2:
                        totalarguments = []
                        splitarguments = depnotifyarguments.split(' ')
                        for x in splitarguments:
                            totalarguments.append(x)
                        depnotifystring = 'depnotifycmd = ' \
                            """['/usr/bin/open', '""" + depnotifypath + "', '"\
                            + '--args' + "', '" + \
                            """', '""".join(map(str, totalarguments)) + "']"
                    else:
                        depnotifystring = 'depnotifycmd = ' \
                            """['/usr/bin/open', '""" + depnotifypath + "', '"\
                            + '--args' + """', '""" + depnotifyarguments + "']"
                else:
                    depnotifystring = 'depnotifycmd = ' \
                        """['/usr/bin/open', '""" + depnotifypath + "']"
                iaslog('Launching DEPNotify with: %s' % (depnotifystring))
                depnotifyscript = "#!/usr/bin/python"
                depnotifyscript += '\n' + "import subprocess"
                depnotifyscript += '\n' + depnotifystring
                depnotifyscript += '\n' + 'subprocess.call(depnotifycmd)'
                with open(depnotifyscriptpath, 'wb') as f:
                    f.write(depnotifyscript)
                os.chmod(depnotifyscriptpath, 0777)
                touch(userscripttouchpath)
                while os.path.isfile(userscripttouchpath):
                    iaslog('Waiting for DEPNotify script to complete')
                    time.sleep(0.5)
        # Loop through the items and download/install/run them.
        for item in iajson[stage]:
            # Set the filepath, name and type.
            try:
                if plugin is None:
                    path = item['file']
                name = item['name']
                type = item['type']
            except KeyError as e:
                iaslog('Invalid item %s: %s' % (repr(item), str(e)))
                continue

            if type == 'package':
                iaslog('%s - processing package %s at %s' % (stage, name, path))
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
                    iaslog('Skipping %s - already installed.' % (name))
                else:
                    # Download the package if it isn't already on disk.
                    download_if_needed(item, stage, type, opts,
                                       depnotifystatus)

                    # On userland stage, we want to wait until we are actually
                    # in the user's session.
                    if stage == 'userland':
                        if len(iajson['userland']) > 0:
                            while (getconsoleuser()[0] is None
                                   or getconsoleuser()[0] == u'loginwindow'
                                   or getconsoleuser()[0] == u'_mbsetupuser'):
                                iaslog('Detected SetupAssistant in userland '
                                       'stage - delaying install until user '
                                       'session.')
                                time.sleep(1)
                    iaslog('Installing %s from %s' % (name, path))
                    if opts.depnotify:
                        if stage == 'setupassistant':
                            iaslog(
                                'Skipping DEPNotify notification due to '
                                'setupassistant.')
                        else:
                            if depnotifystatus:
                                deplog('Status: Installing: %s' % (name))
                    # Install the package
                    installerstatus = installpackage(item['file'])
            elif type == 'rootscript':
                iaslog('%s - processing rootscript %s at %s' %
                      (stage, name, path))
                if 'url' in item:
                    download_if_needed(item, stage, type, opts,
                                       depnotifystatus)
                iaslog('Starting root script: %s' % (path))
                try:
                    donotwait = item['donotwait']
                except KeyError as e:
                    donotwait = False
                if opts.depnotify:
                    if depnotifystatus:
                        deplog('Status: Installing: %s' % (name))
                if stage == 'preflight':
                    preflightrun = runrootscript(path, donotwait)
                    if preflightrun:
                        iaslog('Preflight passed all checks. Skipping run.')
                        userid = str(getconsoleuser()[1])
                        cleanup(iapath, ialdpath, ldidentifier, ialapath,
                                laidentifier, userid, reboot)
                    else:
                        iaslog('Preflight did not pass all checks. '
                                'Continuing run.')
                        continue
                runrootscript(path, donotwait)
            elif type == 'userscript':
                iaslog('%s - processing userscript %s at %s' %
                      (stage, name, path))
                if stage == 'setupassistant':
                    iaslog('Detected setupassistant and user script. '
                           'User scripts cannot work in setupassistant stage! '
                           'Removing %s' % path)
                    os.remove(path)
                    pass
                if 'url' in item:
                    download_if_needed(item, stage, type, opts,
                                       depnotifystatus)
                iaslog('Triggering LaunchAgent for user script: %s' % (path))
                touch(userscripttouchpath)
                if opts.depnotify:
                    if depnotifystatus:
                        deplog('Status: Installing: %s' % (name))
                while os.path.isfile(userscripttouchpath):
                    iaslog('Waiting for user script to complete: %s' % (path))
                    time.sleep(0.5)
            elif type == 'plugin':
                iaslog('%s - processing %s, requires plugin' % (stage, name))
                # check if a plugin was found and loaded
                if plugin is None:
                    iaslog('Error: %s requires plugin, but no plugin was found '
                           'so skipping' % (name))
                    pass
                else:
                    if opts.depnotify:
                        if depnotifystatus:
                            deplog('Status: Installing: %s' % (name))
                    iaslog('%s requires plugin. %s is loaded' % (name, plugin))
                    iaslog('Processing item through plugin')
                    # plugin module must have process_item function
                    plugin.process_item(item)


    # Trigger the final DEPNotify events
    if opts.depnotify:
        for varg in opts.depnotify:
            notification = str(varg)
            if any(x in notification for x in deptriggers):
                iaslog('Sending %s to DEPNotify' % (str(notification)))
                deplog(notification)
            else:
                iaslog(
                    'Skipping DEPNotify notification event due to completion.')

    # Cleanup and trigger a reboot if required.
    userid = str(getconsoleuser()[1])
    cleanup(iapath, ialdpath, ldidentifier, ialapath, laidentifier, userid,
            reboot)

    if reboot:
        iaslog('Triggering reboot')
        subprocess.call(['/sbin/shutdown', '-r', 'now'])


if __name__ == '__main__':
    import_plugin_middleware()
    main()
