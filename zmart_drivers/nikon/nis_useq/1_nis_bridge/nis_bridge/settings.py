"""Every constant of the bridge, in one place.

Nothing else in this package holds a number or a name that one might want to
change; they are all here, so a test or a slow instrument can be met by editing
one file. Times are seconds, distances micrometres.
"""

# -- the connection ----------------------------------------------------------------
HOST = "127.0.0.1"  # the bridge only ever listens on this computer
PORT = 54470
REQUEST_TIMEOUT_S = 30.0  # how long a client waits for an ordinary request
SNAP_TIMEOUT_S = 120.0  # one capture and save
FOCUS_TIMEOUT_S = 300.0  # the NIS image-based focus sweep
REPLY_MARGIN_S = 5.0  # extra time for the reply itself to arrive after NIS is done

# -- inside NIS-Elements --------------------------------------------------------------
PFS_SETTLE_S = 8.0  # how long set_pfs waits for the Perfect Focus System to lock
PFS_ON_STATUSES = (1, 5, 6)  # Stg_GetPFSStatus values that mean "switched on"
AUTOFOCUS_RANGE_UM = 50.0  # the image-based sweep, when the request gives no range
AUTOFOCUS_SPEED = 30  # its speed, 0 (slow, thorough) to AUTOFOCUS_MAX_SPEED
AUTOFOCUS_MAX_SPEED = 90
PUMP_WAIT_S = 0.05  # how long one macro-loop pass waits for a request to arrive
SERVE_POLL_S = 0.05  # how often the socket thread checks for shutdown
STALE_SERVER_S = 2.0  # a server not pumped for this long is from an earlier macro run
LOG_FILE = "nis-bridge.log"  # in the Windows temp folder

# -- NIS function arguments ----------------------------------------------------------
TIFF_ALL_LAYERS = 18  # ImageSaveAs: file type
CLOSE_WITHOUT_ASKING = 2  # CloseCurrentDocument: do not ask about unsaved changes
INFOSTR_VERSION = 1  # Get_InfoStr: the NIS version string
