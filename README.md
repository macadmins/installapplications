# InstallApplications
![InstallApplications icon](/icon/installapplications.png?raw=true)

InstallApplications is an alternative to tools like [PlanB](https://github.com/google/macops-planb) where you can dynamically download packages for use with `InstallApplication`. This is useful for DEP bootstraps, allowing you to have a significantly reduced initial package that can easily be updated without repackaging your initial package.

## MDM's that support Custom DEP
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
2. InstallApplications (this tool) will install and load it's LaunchDaemon.
2. InstallApplications (this tool) will install and load it's LaunchAgent if in the proper context (installed outside of SetupAssistant).
3. InstallApplications will begin to install your setupassistant packages (if configured) during the SetupAssistant.
4. If userland packages are configured, InstallApplications will wait until the user is in their active session before installing.
6. InstallApplications will gracefully exit and kill it's process.

## Stages
There are currently two stages of packages:
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
If you need to install IA's to another folder, you can modify the munki-pkg `payload`, but you will also need to modify the launchdaemon plist's `iapath` argument.

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

You may have more than one package in each stage. Packages will be deployed in alphabetical order, not listed order, so if you want packages installed in a certain order, begin their file names with 1-, 2-, 3- as the case may be.

### Creating your JSON

Using `generatejson.py` you can automatically generate the json with the file, hash, and name keys populated (you'll need to upload the packages to a server and update the url keys).
In order to do this, simply organize your packages in lowercase directories in a "root directory" as shown below:
```
.
├── rootdir
│   ├── setupassistant
│   │   └── setupassistant.pkg
│   ├── userland
│   │   └── userland.py
│   │   └── userland.pkg
```

Then run the tool:
```
python generatejson.py --rootdir /path/to/rootdir
```
The bootstrap.json will be saved in the rootdir. If you want to save it elsewhere, use `--outputdir`:
```
python generatejson.py --rootdir /path/to/rootdir --outputdir /path/to/outputdir
```
