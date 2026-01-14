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

sys.path.append("/Library/installapplications")
# PEP8 can really be annoying at times.
import gurl  # noqa


g_dry_run = False


def _cmp(x, y):
    """
    Replacement for built-in function cmp that was removed in Python 3

    Compare the two objects x and y and return an integer according to
    the outcome. The return value is negative if x < y, zero if x == y
    and strictly positive if x > y.
    """
    return (x > y) - (x < y)


class LooseVersion():
    '''Class based on distutils.version.LooseVersion to compare things like
    "10.6" and "10.6.0" as equal'''

    component_re = re.compile(r'(\d+ | [a-z]+ | \.)', re.VERBOSE)

    def parse(self, vstring):
        """parse function from distutils.version.LooseVersion"""
        # I've given up on thinking I can reconstruct the version string
        # from the parsed tuple -- so I just store the string here for
        # use by __str__
        self.vstring = vstring
        components = [x for x in self.component_re.split(vstring) if x and x != '.']
        for i, obj in enumerate(components):
            try:
                components[i] = int(obj)
            except ValueError:
                pass

        self.version = components

    def __str__(self):
        """__str__ function from distutils.version.LooseVersion"""
        return self.vstring

    def __repr__(self):
        """__repr__ function adapted from distutils.version.LooseVersion"""
        return "MunkiLooseVersion ('%s')" % str(self)

    def __init__(self, vstring=None):
        """init method"""
        if vstring is None:
            # treat None like an empty string
            self.parse('')
        if vstring is not None:
            try:
                if isinstance(vstring, unicode):
                    # unicode string! Why? Oh well...
                    # convert to string so version.LooseVersion doesn't choke
                    vstring = vstring.encode('UTF-8')
            except NameError:
                # python 3
                pass
            self.parse(str(vstring))

    def _pad(self, version_list, max_length):
        """Pad a version list by adding extra 0 components to the end
        if needed"""
        # copy the version_list so we don't modify it
        cmp_list = list(version_list)
        while len(cmp_list) < max_length:
            cmp_list.append(0)
        return cmp_list

    def _compare(self, other):
        """Compare MunkiLooseVersions"""
        if not isinstance(other, LooseVersion):
            other = LooseVersion(other)

        max_length = max(len(self.version), len(other.version))
        self_cmp_version = self._pad(self.version, max_length)
        other_cmp_version = self._pad(other.version, max_length)
        cmp_result = 0
        for index, value in enumerate(self_cmp_version):
            try:
                cmp_result = _cmp(value, other_cmp_version[index])
            except TypeError:
                # integer is less than character/string
                if isinstance(value, int):
                    return -1
                return 1
            if cmp_result:
                return cmp_result
        return cmp_result

    def __hash__(self):
        """Hash method"""
        return hash(self.version)

    def __eq__(self, other):
        """Equals comparison"""
        return self._compare(other) == 0

    def __ne__(self, other):
        """Not-equals comparison"""
        return self._compare(other) != 0

    def __lt__(self, other):
        """Less than comparison"""
        return self._compare(other) < 0

    def __le__(self, other):
        """Less than or equals comparison"""
        return self._compare(other) <= 0

    def __gt__(self, other):
        """Greater than comparison"""
        return self._compare(other) > 0

    def __ge__(self, other):
        """Greater than or equals comparison"""
        return self._compare(other) >= 0


def iaslog(text):
    try:
        NSLog("[InstallApplications] %s" % text)
    except Exception:
        print(text)
        pass


def getconsoleuser():
    cfuser = SCDynamicStoreCopyConsoleUser(None, None, None)
    return cfuser


def is_apple_silicon():
    """Returns True if we're running on Apple Silicon"""
    # ref: https://github.com/munki/munki/commit/8d5472633d01eb1514a4255f2418b6100e44bef6
    arch = os.uname()[4]
    if arch == "x86_64":
        # we might be natively Intel64, or running under Rosetta.
        # os.uname()[4] returns the current execution arch, which under Rosetta
        # will be x86_64. Since what we want here is the _native_ arch, we're
        # going to use a hack for now to see if we're natively arm64
        uname_version = os.uname()[3]
        if "ARM64" in uname_version:
            arch = "arm64"
    return arch == "arm64"


def validate_skip_if(criteria):
    if "arm64" in criteria or "apple_silicon" in criteria:
        return is_apple_silicon()
    elif "x86_64" in criteria or "intel" in criteria:
        return not is_apple_silicon()
    else:
        return False


def pkgregex(pkgpath):
    try:
        # capture everything after last / in the pkg filepath
        pkgname = re.compile(r"[^/]+$").search(pkgpath).group(0)
        return pkgname
    except AttributeError as IndexError:
        return pkgpath


def installpackage(packagepath):
    try:
        cmd = ["/usr/sbin/installer", "-verboseR", "-pkg", packagepath, "-target", "/"]
        if g_dry_run:
            iaslog("Dry run installing package: %s" % packagepath)
            return 0
        proc = subprocess.Popen(
            cmd,
            shell=False,
            bufsize=-1,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        output, rcode = proc.communicate(), proc.returncode
        installlog = output[0].split("\n")
        # Filter all blank lines after the split.
        for line in [_f for _f in installlog if _f]:
            # Replace any instances of % with a space and any elipsis with
            # a blank line since NSLog can't handle these kinds of characters.
            # Hopefully this is the only bad characters we will ever run into.
            logline = line.replace("%", " ").replace("\xe2\x80\xa6", "")
            iaslog(logline)
        return rcode
    except Exception:
        pass


def checkreceipt(packageid):
    try:
        cmd = ["/usr/sbin/pkgutil", "--pkg-info-plist", packageid]
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        output = proc.communicate()
        receiptout = output[0]
        if receiptout:
            plist = plistlib.loads(receiptout)
            version = plist["pkg-version"]
        else:
            version = "0.0.0.0.0"
        return version
    except Exception:
        version = "0.0.0.0.0"
        return version


def gethash(filename):
    hash_function = hashlib.sha256()
    if not os.path.isfile(filename):
        return "NOT A FILE"

    fileref = open(filename, "rb")
    while 1:
        chunk = fileref.read(2 ** 16)
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


def process_request_options(options):
    """
    Checks ia folder for a file that starts with middleware.
    If the file exists options dict is changed.
    Taken from:
    https://github.com/munki/munki/blob/main/code/client/munkilib/fetch.py
    """
    middleware_file = None
    ia_dir = os.path.realpath(os.path.dirname(sys.argv[0]))
    for name in os.listdir(ia_dir):
        if name.startswith('middleware'):
            middleware_file = os.path.splitext(name)[0]
    if middleware_file:
        globals()['middleware'] = __import__(middleware_file,
                                             fromlist=[middleware_file])
        # middleware module must have this function
        options = middleware.process_request_options(options)
    return options


def downloadfile(options):
    # Process options if middleware exists
    options = process_request_options(options)
    connection = gurl.Gurl.alloc().initWithOptions_(options)
    percent_complete = -1
    bytes_received = 0
    connection.start()
    try:
        filename = options["name"]
    except KeyError:
        iaslog("No 'name' key defined in json for %s" % pkgregex(options["file"]))
        sys.exit(1)

    try:
        while not connection.isDone():
            if connection.destination_path:
                # only print progress info if we are writing to a file
                if connection.percentComplete != -1:
                    if connection.percentComplete != percent_complete:
                        percent_complete = connection.percentComplete
                        iaslog(
                            "Downloading %s - Percent complete: %s "
                            % (filename, percent_complete)
                        )
                elif connection.bytesReceived != bytes_received:
                    bytes_received = connection.bytesReceived
                    iaslog(
                        "Downloading %s - Bytes received: %s "
                        % (filename, bytes_received)
                    )

    except (KeyboardInterrupt, SystemExit):
        # safely kill the connection then fall through
        connection.cancel()
    except Exception:  # too general, I know
        # Let us out! ... Safely! Unexpectedly quit dialogs are annoying ...
        connection.cancel()
        # Re-raise the error
        raise

    if connection.error is not None:
        iaslog(
            "Error: %s %s "
            % (
                str(connection.error.code()),
                str(connection.error.localizedDescription()),
            )
        )
        if connection.SSLerror:
            iaslog("SSL error: %s " % (str(connection.SSLerror)))
    if connection.response is not None:
        iaslog("Status: %s " % (str(connection.status)))
        iaslog("Headers: %s " % (str(connection.headers)))
    if connection.redirection != []:
        iaslog("Redirection: %s " % (str(connection.redirection)))


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

    del parser.rargs[: len(value)]
    setattr(parser.values, option.dest, value)


def runrootscript(pathname, donotwait):
    """Runs script located at given pathname"""
    if g_dry_run:
        iaslog("Dry run executing root script: %s" % pathname)
        return True
    try:
        if donotwait:
            iaslog("Do not wait triggered")
            proc = subprocess.Popen(pathname)
            iaslog("Running Script: %s " % pathname)
        else:
            iaslog("Running Script: %s " % pathname)
            proc = subprocess.Popen(
                pathname, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            (out, err) = proc.communicate()
            iaslog("Output on stdout:")
            iaslog(out.decode("utf-8"))
            if err and proc.returncode == 0:
                iaslog("Output on stderr but ran successfully:")
                iaslog(err.decode("utf-8"))
            elif proc.returncode > 0:
                iaslog("Received non-zero exit code:")
                iaslog(err.decode("utf-8"))
                return False
    except OSError as err:
        iaslog("Failure running script:")
        iaslog(str(err.decode("utf-8")))
        return False
    return True


def runuserscript(iauserscriptpath):
    files = os.listdir(iauserscriptpath)
    for file in files:
        pathname = os.path.join(iauserscriptpath, file)
        if g_dry_run:
            iaslog("Dry run executing user script: %s" % pathname)
            os.remove(pathname)
            return True
        try:
            iaslog("Running Script: %s " % pathname)
            proc = subprocess.Popen(
                pathname, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            (out, err) = proc.communicate()
            iaslog("Output on stdout:")
            iaslog(out.decode("utf-8"))
            if err and proc.returncode == 0:
                iaslog("Output on stderr but ran successfully:")
                iaslog(err.decode("utf-8"))
            elif proc.returncode > 0:
                iaslog("Received non-zero exit code:")
                iaslog(err.decode("utf-8"))
                return False
        except OSError as err:
            iaslog("Failure running script:")
            iaslog(str(err.decode("utf-8")))
            return False
        os.remove(pathname)
        return True
    else:
        iaslog("No user scripts found!")
        return False


def download_if_needed(item, stage, type, retries, retrywait, opts):
    # Process item if middleware exists
    item = process_request_options(item)
    # Check if the file exists and matches the expected hash.
    path = item["file"]
    name = item["name"]
    hash = item["hash"]
    itemurl = item["url"]
    while not (os.path.isfile(path) and hash == gethash(path)):
        # Check if additional headers are being passed and add
        # them to the dictionary.
        if opts.headers:
            item.update({"additional_headers": {"Authorization": opts.headers}})
        # Check if we need to follow redirects.
        if opts.follow_redirects:
            item.update({"follow_redirects": True})
        # Download the file once:
        iaslog("Starting download: %s" % urllib.parse.unquote(itemurl))
        downloadfile(item)
        # Wait half a second to process
        time.sleep(0.5)
        # Check the files hash and redownload until it's
        # correct. Bail after three times and log event.
        failsleft = retries
        while not hash == gethash(path):
            iaslog(
                "Hash failed for %s - received: %s expected"
                ": %s" % (name, gethash(path), hash)
            )
            iaslog("Waiting %s seconds before attempting download again..." % retrywait)
            time.sleep(retrywait)
            downloadfile(item)
            failsleft -= 1
            if failsleft == 0:
                iaslog("Hash retry failed for %s: exiting!" % name)
                cleanup(1)
        # Time to install.
        iaslog("Hash validated - received: %s expected: %s" % (gethash(path), hash))
        # Fix script permissions.
        if os.path.splitext(path)[1] != ".pkg":
            os.chmod(path, 0o755)
        if type == "userscript":
            os.chmod(path, 0o777)


def touch(path):
    try:
        touchfile = ["/usr/bin/touch", path]
        proc = subprocess.Popen(
            touchfile, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        touchfileoutput, err = proc.communicate()
        os.chmod(path, 0o777)
        return touchfileoutput
    except Exception:
        return None


def cleanup(exit_code):
    # Attempt to remove the LaunchDaemon
    iaslog("Attempting to remove LaunchDaemon: %s" % ialdpath)
    try:
        os.remove(ialdpath)
    except:  # noqa
        pass

    # Attempt to remove the LaunchAgent
    iaslog("Attempting to remove LaunchAgent: %s" % ialapath)
    try:
        os.remove(ialapath)
    except:  # noqa
        pass

    # Attempt to remove the launchagent from the user's list
    iaslog("Targeting user id for LaunchAgent removal: %s" % userid)
    iaslog("Attempting to remove LaunchAgent: %s" % laidentifier)
    launchctl(
        "/bin/launchctl", "asuser", userid, "/bin/launchctl", "remove", laidentifier
    )

    # Trigger a delayed reboot of 5 seconds
    if reboot:
        iaslog("Triggering reboot")
        rebootcmd = [
            "/usr/bin/osascript",
            "-e",
            "delay 5",
            "-e",
            'tell application "System Events" to restart',
        ]
        try:
            subprocess.Popen(rebootcmd, preexec_fn=os.setpgrp)
        except:  # noqa
            pass

    # Attempt to kill InstallApplications' path
    iaslog("Attempting to remove InstallApplications directory: %s" % iapath)
    try:
        shutil.rmtree(iapath)
    except:  # noqa
        pass

    iaslog("Attempting to remove LaunchDaemon: %s" % ldidentifier)
    launchctl("/bin/launchctl", "remove", ldidentifier)
    iaslog("Cleanup done. Exiting.")
    sys.exit(exit_code)


def write_item_total_runtime(stage, item_name, item_start_time):
    item_runtime = round(time.time() - item_start_time, 2)
    iaslog("%s item ran for %s seconds" % (item_name, item_runtime))
    ias_item_runtimes_dict[stage].update({item_name: item_runtime})
    with open(ias_item_runtimes_plist, 'wb') as ias_runtimes_file:
        plistlib.dump(ias_item_runtimes_dict, ias_runtimes_file)


def main():
    # Options
    usage = "%prog [options]"
    o = optparse.OptionParser(usage=usage)
    o.add_option("--jsonurl", default=None, help=("Required: URL to json file."))
    o.add_option(
        "--dry-run",
        default=False,
        help=("Optional: Dry run (for testing)."),
        action="store_true",
    )
    o.add_option(
        "--follow-redirects",
        default=False,
        help=("Optional: Follow HTTP redirects."),
        action="store_true",
    )
    o.add_option("--headers", default=None, help=("Optional: Auth headers"))
    o.add_option(
        "--iapath",
        default="/Library/installapplications",
        help=("Optional: Specify InstallApplications package path."),
    )
    o.add_option(
        "--laidentifier",
        default="com.erikng.installapplications.user",
        help=("Optional: Specify LaunchAgent identifier."),
    )
    o.add_option(
        "--ldidentifier",
        default="com.erikng.installapplications",
        help=("Optional: Specify LaunchDaemon identifier."),
    )
    o.add_option(
        "--reboot",
        default=False,
        help=("Optional: Trigger a reboot."),
        action="store_true",
    )
    o.add_option(
        "--skip-validation",
        default=False,
        help=("Optional: Skip bootstrap.json validation."),
        action="store_true",
    )
    o.add_option(
        "--userscript",
        default=None,
        help=("Optional: Trigger a user script run."),
        action="store_true",
    )

    opts, args = o.parse_args()

    # Dry run that doesn't actually run or install anything.
    if opts.dry_run:
        global g_dry_run
        g_dry_run = True

    # Check for root and json url.
    if opts.jsonurl:
        jsonurl = opts.jsonurl
        if not g_dry_run and (os.getuid() != 0):
            print("InstallApplications requires root!")
            sys.exit(1)
    else:
        if opts.userscript:
            pass
        else:
            iaslog("No JSON URL specified!")
            sys.exit(1)

    # Begin logging events
    iaslog("Beginning InstallApplications run")

    # installapplications variables
    global iapath
    iapath = opts.iapath
    iauserscriptpath = os.path.join(iapath, "userscripts")
    iatmppath = "/var/tmp/installapplications"
    ialogpath = "/var/log/installapplications"
    iaslog("InstallApplications path: %s" % iapath)
    global ldidentifier
    ldidentifier = opts.ldidentifier
    ldidentifierplist = opts.ldidentifier + ".plist"
    global ialdpath
    ialdpath = os.path.join("/Library/LaunchDaemons", ldidentifierplist)
    iaslog("InstallApplications LaunchDaemon path: %s" % ialdpath)
    global laidentifier
    laidentifier = opts.laidentifier
    laidentifierplist = opts.laidentifier + ".plist"
    global ialapath
    ialapath = os.path.join("/Library/LaunchAgents", laidentifierplist)
    iaslog("InstallApplications LaunchAgent path: %s" % ialapath)

    global userid
    userid = str(getconsoleuser()[1])
    global reboot
    reboot = opts.reboot
    global ias_item_runtimes_dict
    ias_item_runtimes_dict = {}
    global ias_item_runtimes_plist
    ias_item_runtimes_plist = os.path.join(ialogpath, 'ia_item_runtimes.plist')

    # hardcoded json fileurl path
    jsonpath = os.path.join(iapath, "bootstrap.json")
    iaslog("InstallApplications json path: %s" % jsonpath)

    # User script touch path
    userscripttouchpath = "/var/tmp/installapplications/.userscript"

    if opts.userscript:
        iaslog("Running in userscript mode")
        uscript = runuserscript(iauserscriptpath)
        if uscript:
            os.remove(userscripttouchpath)
            sys.exit(0)
        else:
            iaslog("Failed to run user script!")
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
    json_data = {"url": jsonurl, "file": jsonpath, "name": "Bootstrap.json"}

    # Grab auth headers if they exist and update the json_data dict.
    if opts.headers:
        headers = {"Authorization": opts.headers}
        json_data.update({"additional_headers": headers})

    # Check if we need to follow redirects.
    if opts.follow_redirects:
        json_data.update({"follow_redirects": True})

    # Delete the bootstrap file if it exists, to ensure it's up to date.
    if not opts.skip_validation:
        if os.path.isfile(jsonpath):
            iaslog("Removing and redownloading bootstrap.json")
            os.remove(jsonpath)

    # If the file doesn't exist, grab it and wait half a second to save.
    while not os.path.isfile(jsonpath):
        iaslog("Starting download: %s" % urllib.parse.unquote(json_data["url"]))
        downloadfile(json_data)
        time.sleep(0.5)

    # Load up file to grab all the items.
    iajson = json.loads(open(jsonpath).read())

    # Set the stages
    stages = ["preflight", "setupassistant", "userland"]

    # Process all stages
    for stage in stages:
        if stage not in ias_item_runtimes_dict.keys():
            ias_item_runtimes_dict[stage] = {}
        iaslog("Beginning %s" % stage)
        if stage == "preflight":
            # Ensure we actually have a preflight key in the json
            try:
                iajson["preflight"]
            except KeyError:
                iaslog("No preflight stage found: skipping.")
                continue
        # Loop through the items and download/install/run them.
        for item in iajson[stage]:
            # Set the filepath, name and type.
            try:
                path = item["file"]
                name = item["name"]
                type = item["type"]
            except KeyError as e:
                iaslog("Invalid item %s: %s" % (repr(item), str(e)))
                continue
            # Set number or retries, and wait interval between retries
            try:
                retries = item["retries"]
            except KeyError as e:
                retries = 3
            try:
                retrywait = item["retrywait"]
            except KeyError as e:
                retrywait = 5
            iaslog("%s processing %s %s at %s" % (stage, type, name, path))
            # On userland stage, we want to wait until we are actually
            # in the user's session.
            if stage == "userland":
                if len(iajson["userland"]) > 0:
                    while (
                        getconsoleuser()[0] is None
                        or getconsoleuser()[0] == "loginwindow"
                        or getconsoleuser()[0] == "_mbsetupuser"
                    ):
                        iaslog(
                            "Detected SetupAssistant in userland "
                            "stage - delaying install until user "
                            "session."
                        )
                        time.sleep(1)

            # Start item runtime timer
            item_runtime_start = time.time()

            if type == "package":
                packageid = item["packageid"]
                version = item["version"]
                try:
                    pkg_required = item["required"]
                except KeyError:
                    pkg_required = False
                try:
                    skip_if = item["skip_if"]
                except KeyError:
                    skip_if = False
                # Compare version of package with installed version and ensure
                # pkg is not a required install
                if (
                    LooseVersion(checkreceipt(packageid)) >= LooseVersion(version)
                    and not pkg_required
                ):
                    iaslog("Skipping %s - already installed." % name)
                # Skip if a declared criteria is met
                elif skip_if and validate_skip_if(skip_if):
                    iaslog(
                        "Skipping %s - passes skip_if criteria: %s" % (name, skip_if)
                    )
                else:
                    # Download the package if it isn't already on disk.
                    download_if_needed(item, stage, type, retries, retrywait, opts)

                    iaslog("Installing %s from %s" % (name, path))
                    # Install the package
                    installpackage(item["file"])
            elif type == "rootscript":
                if "url" in item:
                    download_if_needed(item, stage, type, retries, retrywait, opts)
                iaslog("Starting root script: %s" % path)
                try:
                    donotwait = item["donotwait"]
                except KeyError as e:
                    donotwait = False
                if stage == "preflight":
                    preflightrun = runrootscript(path, donotwait)
                    if preflightrun:
                        iaslog("Preflight passed all checks. Skipping run.")
                        userid = str(getconsoleuser()[1])
                        cleanup(0)
                    else:
                        iaslog("Preflight did not pass all checks. " "Continuing run.")
                        continue

                runrootscript(path, donotwait)
            elif type == "userscript":
                if "url" in item:
                    download_if_needed(item, stage, type, retries, retrywait, opts)
                if stage == "setupassistant":
                    iaslog(
                        "Detected setupassistant and user script. "
                        "User scripts cannot work in setupassistant stage! "
                        "Removing %s" % path
                    )
                    os.remove(path)
                    continue
                iaslog("Triggering LaunchAgent for user script: %s" % path)
                touch(userscripttouchpath)
                while os.path.isfile(userscripttouchpath):
                    iaslog("Waiting for user script to complete: %s" % path)
                    time.sleep(0.5)

            # Log item runtime
            write_item_total_runtime(stage, name, item_runtime_start)
    # Cleanup and send good exit status
    cleanup(0)


if __name__ == "__main__":
    main()
