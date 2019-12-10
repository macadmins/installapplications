# InstallApplications
![InstallApplications icon](/icon/installapplications.png?raw=true)

InstallApplications is an alternative to tools like [PlanB](https://github.com/google/macops-planb) where you can dynamically download packages for use with `InstallApplication`. This is useful for DEP bootstraps, allowing you to have a significantly reduced initial package that can easily be updated without repackaging your initial package.

## Embedded Python
As of v2.0, InstallApplications now uses its own embedded python v3.8. This is due to Apple's upcoming removal of Python2.

Gurl has been updated from the Munki 4.0 release and tested with HTTPs and Basic Authentication. Further testing would be appreciate by the community.

### Embedded Modules
To help admins with their scripts, the following modules have been added:
PyObjC (required for gurl)
Requests (for API driven tools)

Should the need come up for more modules, a PR should be made against the repo with proper justification

### 2to3
`installapplications.py` and `postinstall` have been ran through 2to3 to automatically convert for Python3 compatibility.

### Building embedded python framework

To reduce the size of the git repository, you **must** create your own Python. To do this, simply run the `./build_python_framework.sh` script within the repository.

This process was tested on Catalina only.

```
./build_python_framework.sh

Cloning relocatable-python tool from github...
Cloning into '/tmp/relocatable-python-git'...
remote: Enumerating objects: 20, done.
remote: Counting objects: 100% (20/20), done.
remote: Compressing objects: 100% (14/14), done.
remote: Total 70 (delta 7), reused 16 (delta 6), pack-reused 50
Unpacking objects: 100% (70/70), done.
Downloading https://www.python.org/ftp/python/3.8.0/python-3.8.0-macosx10.9.pkg...

...

Done!
Customized, relocatable framework is at ./Python.framework
Moving Python.framework to InstallApplications payload folder
```

### Package size increases
Unfortunately due to the embedded python, InstallApplications has significantly grown in size, from approximately 35Kb to 27.5 MB. The low size of InstallApplications has traditionally been one of it's greatest strengths, given how fragile `mdmclient` can be, but there is nothing that can be done here.

### Pinning python user/root scripts to embedded Python
Python user/root scripts should be pinned to the embedded Python framework. Moving forward, **scripts not pinned will be unsupported**.

It is recommended that you run `2to3` against your scripts to make them python3 compliant.

`/usr/local/bin/2to3 -w /path/to/script`

Then simply update the shebang on your python scripts to pin against the InstallApplications python framework.

`#!/Library/installapplications/Python.framework/Versions/3.8/bin/python3`

You can find an example on how this was done by looking at InstallApplications' own `postinstall`

## MDMs that support Custom DEP
- AirWatch
- FileWave (please contact them for instructions)
- MicroMDM
- SimpleMDM

### A note about other MDMs
While other MDMs could _technically_ install this tool, the mechanism greatly differs. Other MDMs currently use `InstallApplication` API to install their binary. From here, you could then install this tool.

Unfortunately, by doing this, you lose many of the features of `InstallApplications`, the primary one being speed.

Example: Jamf Pro

Jamf Pro would install the `jamf` binary first, rather than InstallApplications. An admin would need to scope a policy through the console in order to install this tool and it cannot be 100% validated that InstallApplications will be installed during the SetupAssistant process.

## How this process works:
During a DEP SetupAssistant workflow (with a supported MDM), the following will happen:

1. MDM will send a push request utilizing `InstallApplication` to inform the device of a package installation.
2. InstallApplications (this tool) will install and load its LaunchDaemon.
2. InstallApplications (this tool) will install and load its LaunchAgent if in the proper context (installed outside of SetupAssistant).
3. InstallApplications will begin to install your setupassistant packages (if configured) during the SetupAssistant.
4. If userland packages are configured, InstallApplications will wait until the user is in their active session before installing.
6. InstallApplications will gracefully exit and kill its process.

## Stages
There are currently three stages:
#### preflight ####
This stage is designed to only work with a **single rootscript**. This stage is useful for running InstallApplications on previously deployed machines or if you simply want to re-run it.

If the preflight script exits 0, InstallApplications will cleanup/remove itself, bypassing the setupassistant and userland stages.

If the preflight script exits 1 or higher, InstallApplications will continue with the bootstrap process.
#### setupassistant ####
- Packages/rootscripts that should be prioritized for download/installation _and_ can be installed during SetupAssistant, where no user session is present.
#### userland ####
- Packages/rootscripts/userscripts that should be prioritized for download/installation but may need to be installed in the user's context. This could be your UI tooling that informs the user that a DEP workflow is being used. This stage will wait for a user session before installing.

By utilizing setupassistant/userland, you can have **almost instant UI notifications** for your users.

## Notes
- InstallApplications will only begin installing userland when a user session has been started. This is to reduce the likelihood of your packages attempting to start UI elements during SetupAssistant.

### Signing
You will **NEED** to sign this package for use with DEP/MDM. To acquire a signing certificate, join the [Apple Developers Program](https://developer.apple.com).

Open the `build-info.json` file and specify your signing certificate.

```json
"signing_info": {
    "identity": "Mac Installer: Erik Gomez (XXXXXXXXXXX)",
    "timestamp": true
},
```

Note that you cannot use a `Mac Developer:` signing identity as that is used for application signing and not package signing. Attempting to use this will result in the following error:

`An installer signing identity (not an application signing identity) is required for signing flat-style products.)`

### Downloading and running scripts
InstallApplications can now handle downloading and running scripts. Please see below for how to specify the json structure.

For user scripts, you **must** set the folder path to the `userscripts` sub folder. This is due to the folder having world-wide permissions, allowing the LaunchAgent/User to delete the scripts when finished.

```json
"file": "/Library/Application Support/installapplications/userscripts/userland_exampleuserscript.py",
```

## Installing InstallApplications to another folder.
If you need to install IAs to another folder, you can modify the munki-pkg `payload`, but you will also need to modify the launchdaemon plist's `iapath` argument.

```xml
<string>--iapath</string>
<string>/Library/Application Support/installapplications</string>
```

### Configuring LaunchAgent/LaunchDaemon for your json
Simply specify a url to your json file in the LaunchDaemon plist, located in the payload/Library/LaunchDaemons folder in the root of the project.

```xml
<string>--jsonurl</string>
<string>https://domain.tld</string>
```

NOTE: If you alter the name of the LaunchAgent/LaunchDaemon or the Label, you will also need enable the arguments `laidentifier` and `ldidentifier` in the launchdaemon plist, and the `lapath` and `ldpath` varibles in the postinstall script.

```xml
<string>--laidentifier</string>
<string>com.example.installapplications</string>
<string>--ldidentifier</string>
<string>com.example.installapplications</string>
```

#### Optional Reboot
If after installing all of your packages, you want to force a reboot, simply uncomment the flag in the launchdaemon plist.
```xml
<string>--reboot</string>
```

#### Optional Skip Bootstrap.json validation
If you would like to pre-package your bootstrap.json file into your package and not download it, simply uncomment the flag in the launchdaemon plist.
```xml
<string>--skip-validation</string>
```

#### Basic Auth
Currently, Basic Authentication is only supported by using `--headers` flag.

The authentication should be passed as a base64 encoded username:password, including the Basic string.

Example:

```python
import base64

base64.b64encode('test:test')
'dGVzdDp0ZXN0'

up = base64.b64encode('test:test')

print 'Basic ' + up
Basic dGVzdDp0ZXN0
```

In the LaunchDaemon add the following:

```xml
<string>--headers</string>
<string>Basic dGVzdDp0ZXN0</string>
```

### DEPNotify
InstallApplications can work in conjunction with DEPNotify to automatically create and manipulate the progress bar.

InstallApplications will do the following automatically:
 - Determine the progress bar based on the amount of packages in the json (excluding setupassistant)

#### Notes about argument behavior
If you would like to pass more options to DEPNotify, simply pass string arguments exactly as they would be passed to DEPNotify. The `--depnotify` option can be passed an *unlimited* amount of arguments.

```
installapplications.py --depnotify "Command: WindowTitle: InstallApplications is Awesome!" "Command: Quit: Thanks for using InstallApplications and DEPNotify!"
```

If you pass arguments for `Quit` or `Restart`, InstallApplications will ignore these commands until the end of the run.

#### Opening DEPNotify with InstallApplications
If you would like to open DEPNotify, simply pass the `DEPNotifyPath:` argument to the `--depnotify` option.

```
installapplications.py --depnotify "DEPNotifyPath: /path/to/DEPNotify.app"
```

If you need additional arguments to pass to DEPNotify, add `DEPNotifyArguments:` to the `--depnotify` option.

```
installapplications.py --depnotify "DEPNotifyPath: /path/to/DEPNotify.app" "DEPNotifyArguments: -munki"
```

InstallApplications will wait until `userland` to open DEPNotify as the `setupassistant` is used for SetupAssistant.

You can also pass unlimited arguments to DEPNotify.

```
installapplications.py --depnotify "DEPNotifyPath: /path/to/DEPNotify.app" "DEPNotifyArguments: -munki -fullScreen"
```

**By default** InstallApplications will create a `determinate` and show a status for each item in your stages. If you would like to skip this behavior, pass `DEPNotifySkipStatus` to the `--depnotify` options
```
installapplications.py --depnotify "DEPNotifySkipStatus"`
```

#### DEPNotify LaunchDaemon
You can pass unlimited options to DEPNotify that will allow you to set it's various options.

```xml
<string>--depnotify</string>
<string>DEPNotifySkipStatus</string>
<string>Command: WindowTitle: InstallApplications is Awesome!</string>
<string>Command: NotificationOn:</string>
<string>Command: Quit: Thanks for using InstallApplications and DEPNotify!</string>
<string>Command: WindowStyle: ActivateOnStep</string>
<string>DEPNotifyPath: /Applications/Utilities/DEPNotify.app</string>
<string>DEPNotifyArguments: -munki</string>
```

For a list of all DEPNotify options, please go [here](https://gitlab.com/Mactroll/DEPNotify).

Please note that `DEPNotifyPath` and `DEPNotifyArguments` are custom options for this tool only and are not available in DEPNotify.

### Logging
All root actions are logged at `/private/var/log/installapplications.log` as well as through NSLog. You can open up Console.app and search for `InstallApplications` to bring up all of the events.

All user actions are logged at `/var/tmp/installapplications/installapplications.user.log` as well as through NSLog. You can open up Console.app and search for `InstallApplications` to bring up all of the events.

### Building a package
This repository has been setup for use with [munkipkg](https://github.com/munki/munki-pkg). Use `munkipkg` to build your signed installer with the following command:

`./munkipkg /path/to/repository`

### SHA256 hashes
Each package must have a SHA256 hash stored in the JSON. You can easily create hashes with the following command:

`/usr/bin/shasum -a 256 /path/to/pkg`

This guarantees that the package you place on the web for download is the package that gets installed by InstallApplication. If the hash does not match, InstallApplication will attempt to re-download and re-check.

### JSON Structure
The JSON structure is quite simple. You supply the following:
- filepath (currently hardcoded to `/Library/Application Support/installapplications`)
- url (any domain, but it should ideally be https://)
- hash (SHA256)
- name (define a name for the package, for debug logging and DEPNotify)
- version of package (to check package receipts)
- package id (to check for package receipts)
- type of item (currently `rootscript`, `package` or `userscript`)

The following is an example JSON:
```json
{
  "preflight": [
    {
      "donotwait": false,
      "file": "/Library/Application Support/installapplications/preflight_script.py",
      "hash": "sha256 hash",
      "name": "Example Preflight Script",
      "type": "rootscript",
      "url": "https://domain.tld/preflight_script.py"
    }
  ],
  "setupassistant": [
    {
      "file": "/Library/Application Support/installapplications/setupassistant.pkg",
      "url": "https://domain.tld/setupassistant.pkg",
      "packageid": "com.package.setupassistant",
      "version": "1.0",
      "hash": "sha256 hash",
      "name": "setupassistant Package Name",
      "type": "package"
    }
  ],
  "userland": [
    {
      "file": "/Library/Application Support/installapplications/userland.pkg",
      "url": "https://domain.tld/userland.pkg",
      "packageid": "com.package.userland",
      "version": "1.0",
      "hash": "sha256 hash",
      "name": "Stage 1 Package Name",
      "type": "package"
    },
    {
      "file": "/Library/Application Support/installapplications/userland_examplerootscript.py",
      "hash": "sha256 hash",
      "name": "Example Script",
      "type": "rootscript",
      "url": "https://domain.tld/userland_examplerootscript.py"
    },
    {
      "file": "/Library/Application Support/installapplications/userscripts/userland_exampleuserscript.py",
      "hash": "sha256 hash",
      "name": "Example Script",
      "type": "userscript",
      "url": "https://domain.tld/userland_exampleuserscript.py"
    }
  ]
}
```

URLs should not be subject to redirection, or there may be unintended behavior. Please link directly to the URI of the package.

You may have more than one package and script in each stage. Packages and scripts will be deployed in the order listed.

### Creating your JSON

Using `generatejson.py` you can automatically generate the json with the file, hash, and name keys populated (you'll need to upload the packages to a server and update the url keys).

You can pass an unlimited amount of `--item` arguments, each one with the following meta-variables. Please note that currently _all_ of these meta-variables are **required**:
* item-name - required, sets the display name that will show in DEPNotify
* item-path - required, path on the local disk to the item you want to include
* item-stage - required, defaults to userland if not specified
* item-type - required, generatejson will detect package vs script. Scripts default to rootscript, so pass "userscript" to this variable if your item is a userscript.
* item-url - required, if --base-url is set generatejson will auto-generate the URL as base-url/stage/item-file-name. You can override this automatic generation by passing a URL to the item here.
* script-do-not-wait - required, only applies to userscript and rootscript item-types. Defaults to false.


Run the tool:
```
python generatejson.py --base-url https://github.com --output ~/Desktop \
--item \
item-name='preflight' \
item-path='/localpath/preflight.py' \
item-stage='preflight' \
item-type='rootscript' \
item-url='https://github.com/preflight/preflight.py' \
script-do-not-wait=False \
--item \
item-name='setupassistant package' \
item-path='/localpath/package.pkg' \
item-stage='setupassistant' \
item-type='package' \
item-url='https://github.com/setupassistant/package.pkg' \
script-do-not-wait=False \
--item \
item-name='userland user script' \
item-path='/localpath/userscript.py' \
item-stage='userland' \
item-type='userscript' \
item-url='https://github.com/userland/userscript.py' \
script-do-not-wait=True \
```

The bootstrap.json will be saved in the directory specified with `--output`.
