# Target-acquisition operator memory

## Start the website on the microscope PC

The Python command starts both the website and its local server; there is no
separate frontend process.

```powershell
Set-Location "\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\ZMART-microscopy\workflows\target_acquisition"

& "C:\ProgramData\MinicondaZMB\envs\zmart-microscopy\python.exe" `
  .\run_webapp.py `
  --analysis-repo "\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-analysis"
```

Open <http://127.0.0.1:8765/> and keep the PowerShell window open during the
run. To stop safely, first use **Disconnect** in the website, then press
**Ctrl+C** in PowerShell. Saved experiment files remain on disk.
