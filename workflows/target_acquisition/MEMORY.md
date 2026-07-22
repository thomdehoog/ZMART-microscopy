# Target-acquisition operator memory

## Start the website on the microscope PC

Double-click **`start_website.bat`** in this folder. It starts the local
server and opens <http://127.0.0.1:8765/> in the browser by itself. Keep the
console window open during the run. To stop safely, first use **Disconnect**
in the website, then press **Ctrl+C** in the console. Saved experiment files
remain on disk.

The launcher reads this machine's choices from `start_website.local.bat`
(same folder, ignored by git). On the ZMB microscope PC that file contains:

```bat
set "PYTHON=C:\ProgramData\MinicondaZMB\envs\zmart-microscopy\python.exe"
set "ZMART_ARGS=--analysis-repo \\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-analysis"
```

The repository itself lives at
`\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\ZMART-microscopy`.

To try the flow without the microscope, double-click
**`start_website_demo.bat`** instead — it drives the simulated scope and
sample; nothing real moves.
