# Leica LAS X CAM API Runtime

This directory vendors the Leica LAS X CAM API Python connector and its
required .NET assemblies so a clone of the driver can import:

```python
import LasxApi.PYLICamApiConnector as lasx_api
```

The package name is intentionally `LasxApi` because the generated Leica
connector and driver code use that import path. The descriptive name is this
directory's role in the repo: the Leica LAS X CAM API runtime.

Runtime requirement: the Python environment still needs `pythonnet` so
`import clr` works and the .NET assemblies can be loaded. This directory
removes the need to install/copy Leica's connector files into each environment;
it does not replace the Python/.NET bridge.

Files copied from the local LAS X API bundle:

- `PYLICamApiConnector.py`
- `PYLICamApiConnector.dll`
- `LMS.CAM.CORE.dll`
- `LMS.CAM.SHARED.OBJECTS.dll`
- `Newtonsoft.Json.dll`
- `camTools.py`
- `camFormatter.py`

Do not edit the generated connector directly unless replacing it with a newer
Leica-provided version. Connection pacing is configured in
`navigator_expert.core.profiles.LASX_API`.
