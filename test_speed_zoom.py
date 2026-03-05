"""Try all combinations of speed and zoom, report errors with API details."""
import sys
from LasxApi import PYLICamApiConnector as lasx_api
import driver as drv

client = lasx_api.LasxApiClientPyModel
if not client.Connect("PythonClient"):
    print("ERROR: Cannot connect to LAS X")
    sys.exit(1)

# Get current job
jobs = drv.get_jobs(client)
job = next(j["Name"] for j in jobs if j.get("IsSelected"))
print(f"Job: {job}")

# Read current values to restore later
settings = drv.get_job_settings(client, job)
ch = drv.make_changeable_copy(settings)
orig_zoom = ch["zoom"]["current"]
orig_speed = ch["scanSpeed"]["value"]
print(f"Original: zoom={orig_zoom}, speed={orig_speed}")


def read_echo():
    """Read the API echo after a command."""
    echo = client.PyApiCommandEcho.Model
    info = {}
    for attr in ("HasError", "Error", "Result", "Command", "Description",
                 "ErrorDescription", "Message", "ErrorMessage", "Warning",
                 "Info", "Details"):
        try:
            val = getattr(echo, attr, None)
            if val is not None and val != "" and val != False:
                info[attr] = val
        except Exception:
            pass
    return info


def read_zoom():
    """Read current zoom from job settings."""
    s = drv.get_job_settings(client, job)
    c = drv.make_changeable_copy(s)
    return c["zoom"]["current"]


def read_speed():
    """Read current speed from job settings."""
    s = drv.get_job_settings(client, job)
    c = drv.make_changeable_copy(s)
    return c["scanSpeed"]["value"]


zooms = [0.5, 1, 1.5, 2, 3, 4, 5, 7, 10, 15, 20, 30, 48, 64, 80, 96, 100, 128]
speeds = [10, 50, 100, 200, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000]

print(f"\nTesting {len(zooms)} zooms x {len(speeds)} speeds = {len(zooms)*len(speeds)} combos\n")
print(f"{'zoom':>6} {'speed':>6}  {'result':<60}")
print("-" * 80)

errors = []

for zoom in zooms:
    # Set zoom
    try:
        rz = drv.set_zoom(client, job, zoom)
        zoom_ok = rz.get("confirmed", False)
        if not zoom_ok:
            actual = read_zoom()
            echo = read_echo()
            msg = f"zoom={zoom}: UNCONFIRMED (readback={actual})"
            print(f"{zoom:>6} {'--':>6}  {msg}")
            if echo:
                print(f"           ECHO: {echo}")
            for log in rz.get("logs", []):
                print(f"           LOG: {log}")
            errors.append(msg)
            continue
    except Exception as e:
        msg = f"zoom={zoom}: EXCEPTION: {e}"
        print(f"{zoom:>6} {'--':>6}  {msg}")
        errors.append(msg)
        continue

    for speed in speeds:
        try:
            rs = drv.set_scan_speed(client, job, speed)
            confirmed = rs.get("confirmed", False)
            t = rs.get("timing", {}).get("total_s", 0)
            if confirmed:
                print(f"{zoom:>6} {speed:>6}  OK  ({t:.3f}s)")
            else:
                actual = read_speed()
                echo = read_echo()
                msg = f"zoom={zoom} speed={speed}: UNCONFIRMED (readback={actual})"
                print(f"{zoom:>6} {speed:>6}  UNCONFIRMED  ({t:.3f}s) readback={actual}")
                if echo:
                    print(f"           ECHO: {echo}")
                for log in rs.get("logs", []):
                    print(f"           LOG: {log}")
                errors.append(msg)
        except Exception as e:
            msg = f"zoom={zoom} speed={speed}: {e}"
            print(f"{zoom:>6} {speed:>6}  ERROR: {e}")
            errors.append(msg)

# Restore
print(f"\nRestoring zoom={orig_zoom}, speed={orig_speed}...")
try:
    drv.set_zoom(client, job, orig_zoom)
    drv.set_scan_speed(client, job, orig_speed)
    print("Restored.")
except Exception as e:
    print(f"Restore failed: {e}")

# Summary
print(f"\n{'='*80}")
if errors:
    print(f"  {len(errors)} error(s):")
    for e in errors:
        print(f"    - {e}")
else:
    print("  All combinations OK.")
print(f"{'='*80}")
