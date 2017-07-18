# InstallApplications
![InstallApplications icon](/icon/installapplications.png?raw=true)

InstallApplications is an alternative to tools like [PlanB](https://github.com/google/macops-planb) where you can dynamically download packages for use with `InstallApplication`. This is useful for DEP bootstraps, allowing you to have a significantly reduced initial package that can easily be updated without repackaging your initial package.

## Supported MDMs
- AirWatch
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
3. InstallApplications will begin to install your prestage packages (if configured) during the SetupAssistant.
4. If stage1 packages are configured, InstallApplications will wait until the user is in their active session before installing.
5. If stage 2 packages are configured, InstallApplications will install these packages during the user session.
6. InstallApplications will gracefully exit and kill it's process.

## Stages
There are currently three stages of packages:
#### prestage ####
- Packages that should be prioritized for download/installation _and_ can be installed during SetupAssistant, where no user session is present.
#### stage1 ####
- Packages that should be prioritized for download/installation but may need to be installed in the user's context. This could be your UI tooling that informs the user that a DEP workflow is being used. This stage will wait for a user session before installing.
#### stage2 ####
- Packages that need to be installed, but are not needed immediately.
- stage2 begins immediately after the conclusion of stage1.

By utilizing prestage/stage1, you can have **almost instant UI notifications** for your users.

## Notes
- InstallApplications will only begin installing stage1 when a user session has been started. This is to reduce the likelihood of your packages attempting to start UI elements during SetupAssistant.

### Signing
You will **NEED** to sign this package for use with DEP/MDM. To acquire a signing certificate, join the [Apple Developers Program](https://developer.apple.com).

Open the `build-info.json` file and specify your signing certificate.

```json
"signing_info": {
    "identity": "YOUR IDENTITY FROM LOGIN KEYCHAIN",
    "timestamp": true
},
```

### Configuring LaunchDaemon for your json
Simply specify a url to your json file in the LaunchDaemon plist, located in the payload/Library/LaunchDaemons folder in the root of the project.

```xml
<string>--jsonurl</string>
<string>https://domain.tld</string>
```

NOTE: If you alter the name of the LaunchDaemon or the Label, you will also need to alter the variable `ialdpath` in installapplications.py, as well as in the `launchctld` call in the postinstall script.

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

### Building a package
This repository has been setup for use with [munkipkg](https://github.com/munki/munki-pkg). Use `munkipkg` to build your signed installer with the following command:

`./munkipkg /path/to/repository`

### SHA256 hashes
Each package must have a SHA256 hash stored in the JSON. You can easily create hashes with the following command:

`/usr/bin/shasum -a 256 /path/to/pkg`

This guarantees that the package you place on the web for download is the package that gets installed by InstallApplication. If the hash does not match, InstallApplication will attempt to re-download and re-check.

### JSON Structure
The JSON structure is quite simple. You supply the following:
- filepath (currently hardcoded to `/private/tmp/installapplications`)
- url (any domain, but it should ideally be https://)
- hash (SHA256)
- name (define a name for the package, for debug logging and DEPNotify)

The following is an example JSON:
```json
{
  "prestage": [
    {
      "file": "/private/tmp/installapplications/prestage.pkg",
      "url": "https://domain.tld/prestage.pkg",
      "hash": "sha256 hash",
      "name": "PreStage Package Name"
    }
  ],
  "stage1": [
    {
      "file": "/private/tmp/installapplications/stage1.pkg",
      "url": "https://domain.tld/stage1.pkg",
      "hash": "sha256 hash",
      "name": "Stage 1 Package Name"
    }
  ],
  "stage2": [
    {
      "file": "/private/tmp/installapplications/stage2.pkg",
      "url": "https://domain.tld/stage2.pkg",
      "hash": "sha256 hash",
      "name": "Stage 2 Package Name"
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
│   ├── prestage
│   │   └── prestage.pkg
│   ├── stage1
│   │   └── stage1.pkg
│   └── stage2
│   │   └── stage2_1.pkg
│   │   └── stage2_2.pkg
```

Then run the tool:
```
python generatejson.py --rootdir /path/to/rootdir
```
The bootstrap.json will be saved in the rootdir. If you want to save it elsewhere, use `--outputdir`:
```
python generatejson.py --rootdir /path/to/rootdir --outputdir /path/to/outputdir
```
