# InstallApplications
InstallApplications is an alternative to tools like [PlanB](https://github.com/google/macops-planb) where you can dynamically download packages for use with `InstallApplication`. This is useful for DEP bootstraps, allowing you to have a significantly reduced initial package that can easily be updated without repackaging your initial package.

## Stages
There are currently two stages of packages:
- Stage 1
 - Packages that should be prioritized for download/installation. This could be your UI tooling that informs the user that a DEP workflow is being used.
- Stage 2
 - Packages that can be installed _after_ some kind of UI element has been processed.

## Notes
- InstallApplications will only begin Stage 1 when a user session has been started. This is to reduce the likelihood of your packages attempting to start UI elements during SetupAssistant.

### Signing
You will **NEED** to sign this package for use with DEP/MDM.

Open the `build-info.json` file and specify your signing certificate.

```json
"signing_info": {
    "identity": "YOUR IDENTITY FROM LOGIN KEYCHAIN",
    "timestamp": true
},
```

### Configuring LaunchDaemon for your json
Simply specify a url to your json file in the LaunchDaemon plist.

```xml
<string>--jsonurl</string>
<string>https://domain.tld</string>
```

### Building a package
This repository has been setup for use with [munkipkg](https://github.com/munki/munki-pkg).

`./munkipkg /path/to/repository`

### SHA256 hashes
Each package must have a SHA256 hash stored in the JSON. You can easily create hashes with the following command:

`/usr/bin/shasum -a 256 /path/to/pkg`

### JSON Structure
The JSON structure is quite simple. You supply the following:
- filepath (currently hardcoded to `/private/tmp/installapplications`)
- url (any domain, but it should ideally be https://)
- hash (SHA256)

The following is an example JSON:
```json
{
  "stage1": [
    {
      "file": "/private/tmp/installapplications/stage1.pkg",
      "url": "https://domain.tld/stage1.pkg",
      "hash": "sha256 hash"
    }
  ],
  "stage2": [
    {
      "file": "/private/tmp/installapplications/stage2.pkg",
      "url": "https://domain.tld/stage2.pkg",
      "hash": "sha256 hash"
    }
  ]
}
```

## Basic Authentication
If you would like to use basic authentication for your JSON file, in the `installapplications.py` change the following:

```python
# json data for gurl download
json_data = {
        'url': jsonurl,
        'file': jsonpath,
    }
```

### Username/Password
```python
# json data for gurl download
json_data = {
        'url': jsonurl,
        'file': jsonpath,
        'username': 'test',
        'password': 'test',
    }
```

### Headers

```python
# json data for gurl download
json_data = {
        'url': jsonurl,
        'file': jsonpath,
        'additional_headers': {'Authorization': 'Basic dGVzdDp0ZXN0'},
    }
```
