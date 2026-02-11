#!/usr/bin/env python3
"""
lasx_connector.py â€” Leica LAS X microscope API connector.

Implements the :class:`MicroscopeConnector` interface for the Leica
Application Suite X (LAS X) Python API.  All Leica-specific protocol
details (``PYLICamApiConnector``, ``PyApi*`` model objects, CAM interface
mode, etc.) are encapsulated here.

Architecture
------------
    This module is a *backend* for :mod:`microscope_connector`.
    It registers itself automatically on import::

        from microscope_connector import register_backend
        register_backend("lasx", LasXConnector)

    Users never need to import this file directly â€” they call::

        from microscope_connector import initialize_api
        api = initialize_api("lasx", client_name="PythonClient")

    Direct instantiation is still supported for backward compatibility::

        from vendors.lasx.connector import LasXConnector
        connector = LasXConnector()
        connector.connect()

Dependencies
------------
    - ``LasxApi`` (Leica Python API SDK, ships with LAS X â‰¥ 3.7)
    - ``microscope_connector`` (this project)

Metadata
--------
    Author:  Adaptive Feedback Microscopy project
    Version: 1.0.0
    License: MIT
    Python:  >= 3.9
"""

from __future__ import annotations

import concurrent.futures
import json
import threading
from typing import Any, Dict, List, Optional

from microscope_connector import MicroscopeConnector, register_backend

__all__ = ["LasXConnector"]
__version__ = "1.0.0"


class LasXConnector(MicroscopeConnector):
    """
    Thread-safe connector for the Leica LAS X Python API.

    All public query methods return ``None`` on failure rather than raising
    exceptions, making it safe to use in pipelines where the microscope
    software may be unavailable.

    Parameters
    ----------
    client_name : str
        Name shown in LAS X's connected-client list.
    timeout : float
        Default timeout (seconds) for synchronous API calls.
    **kwargs : Any
        Reserved for future use (e.g. ``host``, ``port`` for remote LAS X).

    Examples
    --------
    Via the factory (recommended)::

        from microscope_connector import initialize_api
        api = initialize_api("lasx")

    Direct instantiation::

        from vendors.lasx.connector import LasXConnector
        with LasXConnector() as api:
            print(api.get_hardware_info())
    """

    # â”€â”€ Class-level constants â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    _BACKEND_NAME: str = "lasx"

    # â”€â”€ Initialisation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def __init__(
        self,
        client_name: str = "PythonConnector",
        timeout: float = 15.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(client_name=client_name, timeout=timeout, **kwargs)

    # â”€â”€ Properties â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @property
    def backend_name(self) -> str:
        """Identifier used by the backend registry."""
        return self._BACKEND_NAME

    # â”€â”€ Connection lifecycle â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def connect(self) -> bool:
        """
        Open a connection to the LAS X CAM API.

        Imports the Leica ``PYLICamApiConnector`` SDK, connects, sets the
        interface to CAM-only mode, and verifies with a ping.

        Returns
        -------
        bool
            ``True`` if the connection is live and verified.
        """
        with self._lock:
            if self._connected:
                return True

            try:
                from LasxApi import PYLICamApiConnector as lasxApi

                self.client = lasxApi.LasxApiClientPyModel
                confirmed = self.client.Connect(self.client_name)

                if not confirmed:
                    print(f"  Warning: LAS X API connection not confirmed")
                    self._connected = False
                    return False

                # Set the interface to CAM-only mode and apply
                self.client.PyApiClient.DelayInMilliseconds = 300
                mode = self.client.PyApiSetApiInterfaceToUse.Model.ApiInterfaceToUse
                self.client.PyApiSetApiInterfaceToUse.Model.ApiInterfaceToUse = (
                    type(mode).Only_the_CAM_interface_is_used
                )
                self.client.PyApiSetApiInterfaceToUse.UpdateSync(10)

                # Verify the connection with a status ping
                if self._ping_internal():
                    self._connected = True
                    self._owns_connection = True
                    return True
                else:
                    self._connected = False
                    return False

            except ImportError:
                print("  Warning: LasxApi module not available (is LAS X installed?)")
                self._connected = False
                return False
            except Exception as e:
                print(f"  Warning: LAS X API connection failed â€” {e}")
                self._connected = False
                return False

    def disconnect(self) -> None:
        """
        Close the LAS X API connection.

        Only disconnects if this instance owns the connection (i.e. was not
        created via :meth:`from_existing_client`).
        """
        with self._lock:
            if self._owns_connection and self.client is not None:
                try:
                    self.client.Disconnect()
                except Exception:
                    pass
            self.client = None
            self._connected = False

    def ping(self) -> bool:
        """
        Verify the API is responsive by reading the current scan status.

        Returns
        -------
        bool
            ``True`` if the status read completes within the timeout.
        """
        if not self._connected:
            return False
        with self._lock:
            return self._ping_internal()

    def _ping_internal(self) -> bool:
        """
        Ping without acquiring the lock (called from :meth:`connect`).

        Reads ``PyApiStatusScan.Model.ScanStatus`` in a background thread
        so the call can be timed out even if the .NET interop blocks.
        """
        def _read_status() -> str:
            return str(self.client.PyApiStatusScan.Model.ScanStatus)

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_read_status)
                status = future.result(timeout=self.timeout)
                print(f"  OK: LAS X ping (scan status: {status})")
                return True
        except concurrent.futures.TimeoutError:
            print(f"  Warning: LAS X ping timed out after {self.timeout}s")
            return False
        except Exception as e:
            print(f"  Warning: LAS X ping failed â€” {e}")
            return False

    # â”€â”€ Command execution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def execute_command(
        self,
        command: str,
        timeout: Optional[float] = None,
    ) -> bool:
        """
        Execute a LAS X CAM command by name.

        Parameters
        ----------
        command : str
            Command string (e.g. ``"GetConfocalHardwareInfo"``).
        timeout : float, optional
            Override the default timeout for this call.

        Returns
        -------
        bool
            ``True`` if the command completed without error.
        """
        if not self._connected:
            return False

        timeout = timeout or self.timeout

        with self._lock:
            try:
                self.client.PyApiCommand.Model.Command = command
                confirmed = self.client.PyApiCommand.UpdateSync(int(timeout))

                if self.client.PyApiCommandEcho.Model.HasError:
                    error = self.client.PyApiCommandEcho.Model.Error
                    print(f"  Warning: Command '{command}' error â€” {error}")
                    return False

                return confirmed

            except Exception as e:
                print(f"  Warning: Command '{command}' failed â€” {e}")
                return False

    # â”€â”€ Hardware queries â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def get_hardware_info(self) -> Optional[Dict[str, Any]]:
        """
        Fetch confocal hardware information from LAS X.

        Returns
        -------
        dict or None
            Keys include ``FilterWheels``, ``LightSinks``, ``LightSources``,
            ``Microscope``, ``ScanSpeed``, ``SerialNumber``, ``SystemType``.
        """
        if not self._connected:
            return None

        with self._lock:
            try:
                self.client.PyApiCommand.Model.Command = "GetConfocalHardwareInfo"
                confirmed = self.client.PyApiCommand.UpdateSync(int(self.timeout))

                if self.client.PyApiCommandEcho.Model.HasError:
                    error = self.client.PyApiCommandEcho.Model.Error
                    print(f"  Warning: GetConfocalHardwareInfo error â€” {error}")
                    return None

                if not confirmed:
                    print("  Warning: GetConfocalHardwareInfo timed out")
                    return None

                hw_json = self.client.PyApiGetConfocalHardwareInfo.Model.HWInfo
                return json.loads(hw_json)

            except Exception as e:
                print(f"  Warning: Failed to get hardware info â€” {e}")
                return None

    # â”€â”€ Job queries â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def get_jobs_list(self) -> Optional[List[Dict[str, Any]]]:
        """
        List all acquisition jobs defined in the current LAS X experiment.

        Returns
        -------
        list[dict] or None
            Each dict has ``Name``, ``ID``, ``IsPattern``, ``IsAutofocus``, etc.
        """
        if not self._connected:
            return None

        with self._lock:
            try:
                self.client.PyApiCommand.Model.Command = "GetJobsInformation"
                confirmed = self.client.PyApiCommand.UpdateSync(int(self.timeout))

                if self.client.PyApiCommandEcho.Model.HasError:
                    error = self.client.PyApiCommandEcho.Model.Error
                    print(f"  Warning: GetJobsInformation error â€” {error}")
                    return None

                if not confirmed:
                    print("  Warning: GetJobsInformation timed out")
                    return None

                jobs_json = self.client.PyApiGetJobsInformation.Model.Jobs
                return json.loads(jobs_json)

            except Exception as e:
                print(f"  Warning: Failed to get jobs list â€” {e}")
                return None

    def get_job_settings(
        self,
        job_name: str,
        verbose: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch detailed settings for one acquisition job.

        Uses the two-step LAS X protocol: first set the job name on the
        model, then execute the ``GetJobSettingsByName`` command.

        Parameters
        ----------
        job_name : str
            Exact name of the job (as returned by :meth:`get_jobs_list`).
        verbose : bool
            Print step-by-step debug output.

        Returns
        -------
        dict or None
            Keys include ``pixelSize``, ``imageSize``, ``format``, ``zoom``,
            ``scanSpeed``, ``activeSettings``, ``objective``, etc.
        """
        if not self._connected:
            return None

        with self._lock:
            try:
                # Step 1: Set the job name on the model
                self.client.PyApiGetJobSettingsByName.Model.JobName = job_name
                confirmed = self.client.PyApiGetJobSettingsByName.UpdateAwaitReceipt(
                    int(self.timeout)
                )

                if verbose:
                    print(f"      [DEBUG] Step 1 â€” Set JobName to '{job_name}': {confirmed}")

                if not confirmed:
                    print(f"  Warning: GetJobSettingsByName('{job_name}') step 1 timed out")
                    return None

                # Step 2: Execute the command to fetch the settings
                self.client.PyApiCommand.Model.Command = "GetJobSettingsByName"
                confirmed = self.client.PyApiCommand.UpdateSync(int(self.timeout))

                if verbose:
                    print(f"      [DEBUG] Step 2 â€” Execute command: {confirmed}")

                if self.client.PyApiCommandEcho.Model.HasError:
                    error = self.client.PyApiCommandEcho.Model.Error
                    print(f"  Warning: GetJobSettingsByName('{job_name}') error â€” {error}")
                    return None

                if not confirmed:
                    print(f"  Warning: GetJobSettingsByName('{job_name}') step 2 timed out")
                    return None

                # Read the result
                settings_json = self.client.PyApiGetJobSettingsByName.Model.Settings

                if verbose:
                    length = len(settings_json) if settings_json else 0
                    print(f"      [DEBUG] Settings length: {length}")

                if not settings_json:
                    print(f"  Warning: No settings returned for '{job_name}'")
                    return None

                settings = json.loads(settings_json)

                # Sanity check: did we get the right job?
                returned_job = settings.get("jobName", "")
                if returned_job and returned_job != job_name:
                    print(
                        f"  Warning: API returned settings for '{returned_job}' "
                        f"instead of '{job_name}'"
                    )

                return settings

            except Exception as e:
                print(f"  Warning: Failed to get job settings for '{job_name}' â€” {e}")
                return None


# â”€â”€â”€ Auto-register with the microscope connector framework â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

register_backend("lasx", LasXConnector)


# â”€â”€â”€ Convenience â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def try_connect(
    client_name: str = "PythonConnector",
    timeout: float = 15.0,
) -> Optional[LasXConnector]:
    """
    Try to create a connected :class:`LasXConnector`.

    Returns
    -------
    LasXConnector or None
        A connected instance, or ``None`` if the connection failed.
    """
    connector = LasXConnector(client_name=client_name, timeout=timeout)
    if connector.connect():
        return connector
    return None


# â”€â”€â”€ CLI Test â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


if __name__ == "__main__":
    print("LAS X Connector Test")
    print("=" * 50)

    connector = LasXConnector()

    if connector.connect():
        print(f"\nOK: Connected â€” {connector!r}")

        print("\n--- Hardware Info ---")
        hw = connector.get_hardware_info()
        if hw:
            print(f"  System:     {hw.get('SystemType')}")
            print(f"  Serial:     {hw.get('SerialNumber')}")
            if "Microscope" in hw:
                print(f"  Microscope: {hw['Microscope'].get('name')}")
                print(f"  Objectives: {len(hw['Microscope'].get('objectives', []))}")

        print("\n--- Jobs ---")
        jobs = connector.get_jobs_list()
        if jobs:
            for job in jobs:
                name = job.get("Name")
                is_af = job.get("IsAutofocus", False)
                print(f"  - {name}" + (" [AF]" if is_af else ""))

                if not is_af:
                    settings = connector.get_job_settings(name)
                    if settings:
                        print(f"      Pixel Size: {settings.get('pixelSize')}")
                        print(f"      Image Size: {settings.get('imageSize')}")
                        print(f"      Format:     {settings.get('format')}")

        connector.disconnect()
        print("\nOK: Disconnected")
    else:
        print("\nWarning: Could not connect to LAS X")
        print("  All query methods will return None.")
