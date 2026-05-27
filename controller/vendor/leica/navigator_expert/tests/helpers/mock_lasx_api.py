"""
Mock LAS X API Client
======================
Behavioral mock of the Leica STELLARIS LAS X Python API for integration testing.
Tracks state, validates inputs, returns realistic errors.
"""

import json
import time


# =============================================================================
# Hardware & job defaults
# =============================================================================

_DEFAULT_JOBS = {
    "HiRes": {
        "zoom": {"current": 10.0},
        "scanSpeed": {"value": 400, "isResonant": False},
        "scanMode": "xyz",
        "sequentialMode": "Frame",
        "scanFieldRotation": {"value": 0.0},
        "format": "1024 x 1024",
        "imageSize": "100.0 um x 100.0 um",
        "pixelSize": "0.0977 um x 0.0977 um",
        "xyStage": {"posX": 50000.0, "posY": 30000.0},
        "objective": {
            "name": "HC PL APO 63x/1.40 OIL CS2",
            "magnification": 63,
            "slotIndex": 3,
        },
        "stack": {"begin": -10.0, "end": 10.0, "stepSize": 1.0, "size": 20.0},
        "zPosition": {
            "z-galvo": {"position": 0.0},
            "z-wide": {"position": 0.0},
        },
        "activeSettings": [{
            "index": 0,
            "name": "PMT1",
            "frameAccumulation": 1,
            "frameAverage": 1,
            "lineAccumulation": 1,
            "lineAverage": 1,
            "pinholeAiry": {"value": 1.0},
            "activeDetectors": [{
                "beamRoute": "40;3",
                "name": "HyD S1",
                "gain": {"value": 100.0},
            }],
            "activeLaserLines": [{
                "beamRoute": "30",
                "lineIndex": 0,
                "wavelength": 488,
                "laser": {"name": "OPSL 488"},
                "intensity": {"value": 0.1},
                "shutterOpen": True,
            }],
        }],
    },
    "Overview": {
        "zoom": {"current": 1.0},
        "scanSpeed": {"value": 800, "isResonant": False},
        "scanMode": "xy",
        "sequentialMode": "Frame",
        "scanFieldRotation": {"value": 0.0},
        "format": "512 x 512",
        "imageSize": "1200.0 um x 1200.0 um",
        "pixelSize": "2.3438 um x 2.3438 um",
        "xyStage": {"posX": 50000.0, "posY": 30000.0},
        "objective": {
            "name": "HC PL APO 10x/0.40 CS2",
            "magnification": 10,
            "slotIndex": 1,
        },
        "zPosition": {
            "z-galvo": {"position": 0.0},
            "z-wide": {"position": 0.0},
        },
        "activeSettings": [{
            "index": 0, "name": "PMT1",
            "frameAccumulation": 1, "frameAverage": 1,
            "lineAccumulation": 1, "lineAverage": 1,
            "pinholeAiry": {"value": 1.0},
            "activeDetectors": [{"beamRoute": "40;3", "name": "HyD S1",
                                  "gain": {"value": 100.0}}],
            "activeLaserLines": [{"beamRoute": "30", "lineIndex": 0,
                                   "wavelength": 488, "intensity": {"value": 0.05},
                                   "shutterOpen": True}],
        }],
    },
}

_DEFAULT_HARDWARE = {
    "Microscope": {
        "objectives": [
            {
                "name": "HC PL APO 10x/0.40 CS2",
                "magnification": 10,
                "slotIndex": 1,
                "objectiveNumber": 1,
            },
            {
                "name": "HC PL APO 40x/1.30 OIL CS2",
                "magnification": 40,
                "slotIndex": 2,
                "objectiveNumber": 2,
            },
            {
                "name": "HC PL APO 63x/1.40 OIL CS2",
                "magnification": 63,
                "slotIndex": 3,
                "objectiveNumber": 3,
            },
        ],
    },
    "LightSources": [],
    "LightSinks": [],
}

# Valid parameter ranges
_VALIDATION = {
    "zoom": (0.75, 48.0),
    "scanSpeed": (1, 2600),
    "rotation": (-360.0, 360.0),
    "pinholeAiry": (0.2, 10.0),
    "frameAccumulation": (1, 1024),
    "frameAverage": (1, 1024),
    "lineAccumulation": (1, 1024),
    "lineAverage": (1, 1024),
    "detectorGain": (0.0, 1200.0),
    "laserIntensity": (0.0, 1.0),
}


# =============================================================================
# Mock Model classes
# =============================================================================

class _Model:
    """Generic model that accepts any attribute."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _EchoModel:
    """PyApiCommandEcho.Model — tracks last error."""
    def __init__(self):
        self.HasError = False
        self.Error = ""
        self.Result = 1  # Success

    def set_error(self, msg, result=2):
        self.HasError = True
        self.Error = msg
        self.Result = result

    def set_warning(self, msg):
        self.HasError = True
        self.Error = f"Warning: {msg}"
        self.Result = 1

    def clear(self):
        self.HasError = False
        self.Error = ""
        self.Result = 1


# =============================================================================
# Mock API object — handles UpdateAsync/UpdateSync
# =============================================================================

class _MockApiObject:
    """Mock for a PyApi* command object with Model and dispatch methods."""

    def __init__(self, name, handler, latency=0.001):
        self.Model = _Model()
        self._name = name
        self._handler = handler
        self._latency = latency

    def UpdateAsync(self):
        time.sleep(self._latency)
        self._handler(self.Model)

    def UpdateAwaitReceipt(self, timeout=2):
        """Transport-level ACK — confirms command arrived at LAS X."""
        time.sleep(self._latency)
        self._handler(self.Model)
        return True

    def UpdateSync(self, timeout=15):
        time.sleep(self._latency)
        self._handler(self.Model)
        return True


# =============================================================================
# Mock .NET enum classes — support type(obj).eMember resolution pattern
# =============================================================================

class _MockEnumUnits:
    """Mock for LMS.CAM.CORE.Models.Enumerations.EnumUnits."""
    eUnknown = 0
    eMeter = 1
    eCentimeter = 2
    eMillimeter = 3
    eMicrons = 4

    def __init__(self, val="eUnknown"):
        self._val = val

    def __str__(self):
        return self._val

    def __int__(self):
        return getattr(type(self), self._val, 0)

    def __repr__(self):
        return self._val


class _MockEnumMoveXYMode:
    """Mock for LMS.CAM.CORE.Models.Enumerations.EnumMoveXYMode."""
    eDontMove = 0
    eMoveXY = 2
    eMoveX = 3
    eMoveY = 4

    def __init__(self, val="eDontMove"):
        self._val = val

    def __str__(self):
        return self._val

    def __int__(self):
        return getattr(type(self), self._val, 0)

    def __repr__(self):
        return self._val


class _MockEnumZUseMode:
    """Mock for Z drive mode enum."""
    eUseGalvo = 0
    eUseZWide = 1
    eUseBoth = 2
    eUseMicFineFocus = 3
    eUseMicrotome = 4
    eUseNothing = 5

    def __init__(self, val="eUseGalvo"):
        self._val = val

    def __str__(self):
        return self._val

    def __int__(self):
        return getattr(type(self), self._val, 0)

    def __repr__(self):
        return self._val


# =============================================================================
# MockLasxClient
# =============================================================================

class MockLasxClient:
    """Behavioral mock of LasxApiClientPyModel.

    Tracks microscope state (jobs, settings, stage position, scan status).
    Validates parameters and produces realistic errors.
    Matches the real LAS X API attribute names and command dispatch patterns.

    Usage:
        client = MockLasxClient(latency=0.001)
        client.set_scanning(0.5)  # simulate 500ms scan
    """

    def __init__(self, latency=0.001):
        self._latency = latency
        self._echo = _EchoModel()

        # State
        import copy
        self._jobs = copy.deepcopy(_DEFAULT_JOBS)
        self._hardware = copy.deepcopy(_DEFAULT_HARDWARE)
        self._selected_job = "HiRes"
        self._stage_x = 0.05  # meters
        self._stage_y = 0.03  # meters
        self._scan_status = "eScanIdle"
        self._scan_busy_until = 0.0

        # PyApiCommandEcho — error tracking
        self.PyApiCommandEcho = type("Obj", (), {"Model": self._echo})()

        # PyApiStatus — scan status (direct read)
        self.PyApiStatus = _MockApiObject(
            "Status", lambda m: None, latency)
        self.PyApiStatus.Model = self._make_status_model()

        # PyApiPing — connection health check
        self.PyApiPing = _MockApiObject("Ping", lambda m: None, latency)

        # PyApiCommand — command dispatch channel
        self.PyApiCommand = _MockApiObject(
            "Command", self._handle_command_dispatch, latency)
        self.PyApiCommand.Model.Command = ""

        # Read API objects — use correct property names from real API
        # get_job_settings reads .Settings (not .Result)
        # Handler is no-op: data delivery happens via command channel only.
        # The driver calls UpdateAwaitReceipt as a best-effort push, then
        # clears Settings before dispatching via command channel.
        self.PyApiGetJobSettingsByName = _MockApiObject(
            "GetJobSettings", lambda m: None, latency)
        self.PyApiGetJobSettingsByName.Model.Settings = None
        self.PyApiGetJobSettingsByName.Model.JobName = ""

        # get_hardware_info reads .HWInfo (not .Result)
        self.PyApiGetConfocalHardwareInfo = _MockApiObject(
            "GetHardwareInfo", self._handle_get_hardware_info, latency)
        self.PyApiGetConfocalHardwareInfo.Model.HWInfo = None

        # get_jobs reads .Jobs (not .Result)
        self.PyApiGetJobsInformation = _MockApiObject(
            "GetJobs", self._handle_get_jobs, latency)
        self.PyApiGetJobsInformation.Model.Jobs = None

        # get_xy — direct read, model properties always live
        self._xy_model = self._make_xy_model()
        self.PyApiGetXY = type("Obj", (), {"Model": self._xy_model})()

        # Action API objects
        self.PyApiSelectJobByName = _MockApiObject(
            "SelectJob", self._handle_select_job, latency)
        self.PyApiStartScan = _MockApiObject(
            "StartScan", self._handle_start_scan, latency)
        self.PyApiAcquireJob = _MockApiObject(
            "AcquireJob", self._handle_acquire_job, latency)

        # Move commands — models need enum-like properties
        self.PyApiMoveHardwareXY = _MockApiObject(
            "MoveStage", self._handle_move_stage, latency)
        self.PyApiMoveHardwareXY.Model.RelativePosition = False
        self.PyApiMoveHardwareXY.Model.MoveXyMode = _MockEnumMoveXYMode("eMoveXY")
        self.PyApiMoveHardwareXY.Model.Units = _MockEnumUnits("eMicrons")

        # Set commands — route through generic handler
        set_commands = [
            "PyApiSetZoomByJobName",
            "PyApiSetScanSpeedByJobName",
            "PyApiSetScannerToResonantByJobName",
            "PyApiSetScanModeByJobName",
            "PyApiSetSequentialModeByJobName",
            "PyApiSetScanFieldRotationByJobName",
            "PyApiSetImageSizeByJobName",
            "PyApiSetObjectiveSlotByJobName",
            "PyApiSetZStackDefinitionByJobName",
            "PyApiCommandSetZStackStepSizeByJobName",
            "PyApiSetZStackSizeByJobName",
            "PyApiSetFrameAccumulationByJobName",
            "PyApiSetFrameAverageByJobName",
            "PyApiSetLineAccumulationByJobName",
            "PyApiSetLineAverageByJobName",
            "PyApiSetPinholeAUByJobName",
            "PyApiSetDetectorGainByJobName",
            "PyApiSetDetectorActiveByJobName",
            "PyApiSetLaserIntensityByJobName",
            "PyApiSetLaserShutterByJobName",
            "PyApiAddOrRemoveLaserLineByJobName",
            "PyApiSetFilterWheelSlotByJobName",
            "PyApiSetFilterWheelSpectrumPositionByJobName",
            "PyApiMoveZByJobName",
        ]
        for cmd in set_commands:
            obj = _MockApiObject(cmd, self._make_set_handler(cmd), latency)
            setattr(self, cmd, obj)

        # Set enum-like properties on MoveZ model for enum resolution
        self.PyApiMoveZByJobName.Model.ZUseMode = _MockEnumZUseMode("eUseGalvo")
        self.PyApiMoveZByJobName.Model.Units = _MockEnumUnits("eMicrons")

    def _make_status_model(self):
        """Create a dynamic status model that checks scan timing."""
        client = self

        class StatusModel:
            @property
            def ScanStatus(self):
                if time.monotonic() < client._scan_busy_until:
                    return "eScanStarted"
                return client._scan_status

        return StatusModel()

    def _make_xy_model(self):
        """Create a live XY model that reads current stage position."""
        client = self

        class XYModel:
            @property
            def XPosition(self):
                return client._stage_x

            @XPosition.setter
            def XPosition(self, value):
                pass

            @property
            def YPosition(self):
                return client._stage_y

            @YPosition.setter
            def YPosition(self, value):
                pass

        return XYModel()

    def _sync_stage_to_jobs(self):
        """Keep raw job settings aligned with the global stage position."""
        x_um = self._stage_x * 1e6
        y_um = self._stage_y * 1e6
        for job in self._jobs.values():
            job["xyStage"] = {"posX": x_um, "posY": y_um}

    def _handle_command_dispatch(self, model):
        """Handle PyApiCommand dispatch — triggers the appropriate read handler.

        Results are delivered after a brief delay to match real API async behavior.
        The driver clears result fields after firing, so synchronous delivery
        would get overwritten.

        Exception: GetXY is handled synchronously because the XY model has
        live properties and the driver reads immediately after UpdateSync.
        """
        cmd = getattr(model, "Command", "")

        # Synchronous delivery — the driver clears result fields before
        # dispatching via command channel, then polls. Delivering here
        # (after the clear) ensures the driver sees fresh data.
        if cmd == "GetXY":
            self._echo.clear()
        elif cmd == "GetJobSettingsByName":
            self._handle_get_job_settings(
                self.PyApiGetJobSettingsByName.Model)
        elif cmd == "GetConfocalHardwareInfo":
            self._handle_get_hardware_info(
                self.PyApiGetConfocalHardwareInfo.Model)
        elif cmd == "GetJobsInformation":
            self._handle_get_jobs(self.PyApiGetJobsInformation.Model)

    def set_scanning(self, duration):
        """Simulate scanner being busy for `duration` seconds."""
        self._scan_busy_until = time.monotonic() + duration
        self._scan_status = "eScanIdle"

    def Connect(self, client_name="PythonClient"):
        """Mock connection — always succeeds."""
        return True

    # ── Read handlers ──

    def _handle_get_job_settings(self, model):
        self._echo.clear()
        job_name = getattr(model, "JobName", "")
        if job_name in self._jobs:
            model.Settings = json.dumps(self._jobs[job_name])
        else:
            model.Settings = None

    def _handle_get_hardware_info(self, model):
        self._echo.clear()
        model.HWInfo = json.dumps(self._hardware)

    def _handle_get_jobs(self, model):
        self._echo.clear()
        jobs_list = []
        for name, job in self._jobs.items():
            jobs_list.append({
                "Name": name,
                "IsSelected": name == self._selected_job,
                "ScanMode": job.get("scanMode", "xyz"),
            })
        model.Jobs = json.dumps(jobs_list)

    # ── Action handlers ──

    def _handle_select_job(self, model):
        self._echo.clear()
        job_name = getattr(model, "JobName", "")
        if job_name in self._jobs:
            self._selected_job = job_name
        # else: no error — select_job polls get_jobs to confirm

    def _handle_start_scan(self, model):
        self._echo.clear()
        job_name = getattr(model, "JobName", "")
        if job_name not in self._jobs:
            self._echo.set_error(f"Job '{job_name}' not found")
            return
        # Simulate a short scan
        self._scan_busy_until = time.monotonic() + 0.1

    def _handle_acquire_job(self, model):
        self._echo.clear()
        job_name = getattr(model, "JobName", "")
        if job_name not in self._jobs:
            self._echo.set_error(f"Job '{job_name}' not found")
            return
        # Simulate a short scan
        self._scan_busy_until = time.monotonic() + 0.1

    def _handle_move_stage(self, model):
        self._echo.clear()
        x = getattr(model, "XPosition", self._stage_x)
        y = getattr(model, "YPosition", self._stage_y)
        # Convert to meters based on Units enum
        # 0=eUnknown, 1=eMeter, 2=eCentimeter, 3=eMillimeter, 4=eMicrons
        units = getattr(model, "Units", 1)
        try:
            units_int = int(units)
        except (ValueError, TypeError):
            # .NET enum or string — try to extract int
            u_str = str(units).lower()
            if "micron" in u_str:
                units_int = 4
            elif "milli" in u_str:
                units_int = 3
            elif "centi" in u_str:
                units_int = 2
            else:
                units_int = 1  # default to meters
        scale = {0: 1, 1: 1, 2: 1e-2, 3: 1e-3, 4: 1e-6}.get(units_int, 1)
        self._stage_x = x * scale
        self._stage_y = y * scale
        self._sync_stage_to_jobs()

    # ── Set command dispatch ──

    def _make_set_handler(self, cmd_name):
        def handler(model):
            self._echo.clear()

            # Check scanner busy
            if time.monotonic() < self._scan_busy_until:
                self._echo.set_error(
                    "The parameter cannot be set while the block is being scanned")
                return

            job_name = getattr(model, "JobName", "")
            if job_name not in self._jobs:
                self._echo.set_error(
                    f"CamCommand{cmd_name.replace('PyApi', '')} "
                    f"invalid block identifier")
                return

            job = self._jobs[job_name]

            # Route to specific validation and state update
            if "Zoom" in cmd_name:
                self._set_zoom(model, job)
            elif "ScanSpeed" in cmd_name and "Resonant" not in cmd_name:
                self._set_scan_speed(model, job)
            elif "Resonant" in cmd_name:
                self._set_resonant(model, job)
            elif "ScanMode" in cmd_name:
                self._set_scan_mode(model, job)
            elif "SequentialMode" in cmd_name:
                self._set_sequential_mode(model, job)
            elif "ScanFieldRotation" in cmd_name:
                self._set_rotation(model, job)
            elif "ImageSize" in cmd_name:
                self._set_image_format(model, job)
            elif "ObjectiveSlot" in cmd_name:
                self._set_objective(model, job)
            elif "ZStackDefinition" in cmd_name:
                self._set_z_stack_definition(model, job)
            elif "ZStackStepSize" in cmd_name:
                self._set_z_stack_step_size(model, job)
            elif "ZStackSize" in cmd_name:
                self._set_z_stack_size(model, job)
            elif "FrameAccumulation" in cmd_name:
                self._set_frame_accumulation(model, job)
            elif "FrameAverage" in cmd_name:
                self._set_frame_average(model, job)
            elif "LineAccumulation" in cmd_name:
                self._set_line_accumulation(model, job)
            elif "LineAverage" in cmd_name:
                self._set_line_average(model, job)
            elif "PinholeAU" in cmd_name:
                self._set_pinhole(model, job)
            elif "DetectorGain" in cmd_name:
                self._set_detector_gain(model, job)
            elif "DetectorActive" in cmd_name:
                pass  # no validation
            elif "LaserIntensity" in cmd_name:
                self._set_laser_intensity(model, job)
            elif "LaserShutter" in cmd_name:
                pass  # no validation
            elif "AddOrRemoveLaserLine" in cmd_name:
                pass  # no validation
            elif "FilterWheel" in cmd_name:
                pass  # no validation
            elif "MoveZ" in cmd_name:
                self._handle_move_z(model, job)

            # Keep Model.Settings in sync so the early-exit path in
            # get_job_settings returns fresh data after mutations.
            if not self._echo.HasError:
                self.PyApiGetJobSettingsByName.Model.Settings = json.dumps(job)

        return handler

    # ── Validation + state update ──

    def _set_zoom(self, model, job):
        v = getattr(model, "ZoomValue", None)
        lo, hi = _VALIDATION["zoom"]
        if v is None or v < lo or v > hi:
            self._echo.set_error(
                f"The zoom parameter ({v}) is out of range. "
                f"Valid: [{lo}, {hi}]")
            return
        job["zoom"]["current"] = v

    def _set_scan_speed(self, model, job):
        v = getattr(model, "ScanSpeed", None)
        lo, hi = _VALIDATION["scanSpeed"]
        if v is None or v < lo or v > hi:
            self._echo.set_error(
                f"The scan speed parameter ({v}) is out of range. "
                f"Valid: [{lo}, {hi}]")
            return
        job["scanSpeed"]["value"] = v

    def _set_resonant(self, model, job):
        v = getattr(model, "EnableResonant", None)
        job["scanSpeed"]["isResonant"] = bool(v)

    def _set_scan_mode(self, model, job):
        v = getattr(model, "ScanModeValue", None)
        job["scanMode"] = str(v) if v else job["scanMode"]

    def _set_sequential_mode(self, model, job):
        v = getattr(model, "SequentialMode", None)
        # Accept .NET enum or string
        s = str(v)
        for mode in ("Line", "Frame", "Stack"):
            if mode.lower() in s.lower():
                job["sequentialMode"] = mode
                return
        job["sequentialMode"] = s

    def _set_rotation(self, model, job):
        v = getattr(model, "Rotation", None)
        lo, hi = _VALIDATION["rotation"]
        if v is None or v < lo or v > hi:
            self._echo.set_error(
                f"The rotation parameter ({v}) is out of range.")
            return
        job["scanFieldRotation"]["value"] = v

    def _set_image_format(self, model, job):
        w = getattr(model, "ImageWidth", None)
        h = getattr(model, "ImageHeight", None)
        if w and h:
            job["format"] = f"{w} x {h}"

    def _set_objective(self, model, job):
        slot = getattr(model, "ObjectiveSlotIndex", None)
        for obj in self._hardware["Microscope"]["objectives"]:
            if obj["slotIndex"] == slot:
                job["objective"] = {
                    "name": obj["name"],
                    "magnification": obj["magnification"],
                    "slotIndex": obj["slotIndex"],
                }
                return
        self._echo.set_error(f"Objective slot {slot} not found")

    def _set_z_stack_definition(self, model, job):
        if "stack" not in job or job["stack"] is None:
            job["stack"] = {"begin": None, "end": None,
                            "stepSize": None, "size": None}
        sb = getattr(model, "SetBegin", 2)
        if sb == 1:
            job["stack"]["begin"] = getattr(model, "BeginValue", 0) * 1e6
        se = getattr(model, "SetEnd", 2)
        if se == 1:
            job["stack"]["end"] = getattr(model, "EndValue", 0) * 1e6

    def _set_z_stack_step_size(self, model, job):
        if "stack" not in job or job["stack"] is None:
            job["stack"] = {"begin": None, "end": None,
                            "stepSize": None, "size": None}
        v = getattr(model, "StackStepSize", 0) * 1e6
        job["stack"]["stepSize"] = v

    def _set_z_stack_size(self, model, job):
        if "stack" not in job or job["stack"] is None:
            job["stack"] = {"begin": None, "end": None,
                            "stepSize": None, "size": None}
        v = getattr(model, "StackSize", 0) * 1e6
        job["stack"]["size"] = v

    def _set_frame_accumulation(self, model, job):
        v = getattr(model, "FrameAccumulation", None)
        lo, hi = _VALIDATION["frameAccumulation"]
        if v is None or v < lo or v > hi:
            self._echo.set_error(
                f"The frame accumulation parameter ({v}) is invalid. "
                f"Valid: [{lo}, {hi}]")
            return
        si = getattr(model, "SettingIndex", 0)
        if si < len(job["activeSettings"]):
            job["activeSettings"][si]["frameAccumulation"] = v

    def _set_frame_average(self, model, job):
        v = getattr(model, "FrameAverage", None)
        lo, hi = _VALIDATION["frameAverage"]
        if v is None or v < lo or v > hi:
            self._echo.set_error(
                f"The frame average parameter ({v}) is invalid. "
                f"Valid: [{lo}, {hi}]")
            return
        si = getattr(model, "SettingIndex", 0)
        if si < len(job["activeSettings"]):
            job["activeSettings"][si]["frameAverage"] = v

    def _set_line_accumulation(self, model, job):
        v = getattr(model, "LineAccumulation", None)
        lo, hi = _VALIDATION["lineAccumulation"]
        if v is None or v < lo or v > hi:
            self._echo.set_error(
                f"The line accumulation parameter ({v}) is invalid.")
            return
        si = getattr(model, "SettingIndex", 0)
        if si < len(job["activeSettings"]):
            job["activeSettings"][si]["lineAccumulation"] = v

    def _set_line_average(self, model, job):
        v = getattr(model, "LineAverage", None)
        lo, hi = _VALIDATION["lineAverage"]
        if v is None or v < lo or v > hi:
            self._echo.set_error(
                f"The line average parameter ({v}) is invalid.")
            return
        si = getattr(model, "SettingIndex", 0)
        if si < len(job["activeSettings"]):
            job["activeSettings"][si]["lineAverage"] = v

    def _set_pinhole(self, model, job):
        v = getattr(model, "PinholeAiry", None)
        lo, hi = _VALIDATION["pinholeAiry"]
        si = getattr(model, "SettingIndex", 0)
        if v is not None and (v < lo or v > hi):
            # Clamp + warning (hardware behavior)
            clamped = max(lo, min(hi, v))
            self._echo.set_warning(
                f"pinhole adjusted to nearest valid value: {clamped}")
            if si < len(job["activeSettings"]):
                job["activeSettings"][si]["pinholeAiry"]["value"] = clamped
            return
        if v is not None and si < len(job["activeSettings"]):
            job["activeSettings"][si]["pinholeAiry"]["value"] = v

    def _set_detector_gain(self, model, job):
        v = getattr(model, "GainValue", None)
        br = getattr(model, "BeamRoute", "")
        si = getattr(model, "SettingIndex", 0)
        lo, hi = _VALIDATION["detectorGain"]

        if si < len(job["activeSettings"]):
            dets = job["activeSettings"][si].get("activeDetectors", [])
            det = next((d for d in dets if d["beamRoute"] == br), None)
            if det is None:
                self._echo.set_error(f"Invalid detector: {br}")
                return
            if v is None or v < lo or v > hi:
                self._echo.set_error(
                    f"The detector gain ({v}) is out of range.")
                return
            det["gain"]["value"] = v

    def _set_laser_intensity(self, model, job):
        v = getattr(model, "IntensityValue", None)
        br = getattr(model, "BeamRoute", "")
        si = getattr(model, "SettingIndex", 0)
        lo, hi = _VALIDATION["laserIntensity"]

        if si < len(job["activeSettings"]):
            lasers = job["activeSettings"][si].get("activeLaserLines", [])
            las = next((l for l in lasers if l["beamRoute"] == br), None)
            if las is None:
                self._echo.set_error(f"Invalid light source: {br}")
                return
            if v is None or v < lo or v > hi:
                self._echo.set_error(
                    f"The laser intensity ({v}) is out of range.")
                return
            las["intensity"]["value"] = v

    def _handle_move_z(self, model, job):
        z = getattr(model, "ZPosition", 0)
        units = getattr(model, "Units", 4)
        try:
            units_int = int(units)
        except (ValueError, TypeError):
            u_str = str(units).lower()
            if "micron" in u_str:
                units_int = 4
            elif "milli" in u_str:
                units_int = 3
            else:
                units_int = 1
        # Convert to µm
        to_um = {0: 1e6, 1: 1e6, 2: 1e4, 3: 1e3, 4: 1.0}.get(units_int, 1e6)
        z_um = z * to_um
        # Determine which drive to update (int enum or string)
        z_use = getattr(model, "ZUseMode", None)
        try:
            z_int = int(z_use)
        except (ValueError, TypeError):
            z_int = None
        # Map: 0=eUseGalvo, 1=eUseZWide, 2=eUseBoth
        _ZUSE_INT_MAP = {0: "galvo", 1: "zwide", 2: "both"}
        if z_int is not None and z_int in _ZUSE_INT_MAP:
            z_key = _ZUSE_INT_MAP[z_int]
        else:
            z_str = str(z_use).lower() if z_use is not None else ""
            if "galvo" in z_str:
                z_key = "galvo"
            elif "zwide" in z_str or "wide" in z_str:
                z_key = "zwide"
            elif "both" in z_str:
                z_key = "both"
            else:
                z_key = None
        if "zPosition" not in job:
            job["zPosition"] = {
                "z-galvo": {"position": 0.0},
                "z-wide": {"position": 0.0},
            }
        if z_key == "galvo":
            job["zPosition"]["z-galvo"]["position"] = z_um
        elif z_key == "zwide":
            job["zPosition"]["z-wide"]["position"] = z_um
        elif z_key == "both":
            job["zPosition"]["z-galvo"]["position"] = z_um
            job["zPosition"]["z-wide"]["position"] = z_um
