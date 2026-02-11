#!/usr/bin/env python3
"""
microscope_connector.py â€” Manufacturer-agnostic microscope API connector.

Provides a generic interface for connecting to microscope software APIs.
Manufacturer-specific implementations (Leica LAS X, Zeiss ZEN, Nikon NIS, etc.)
live in separate files and register themselves via the backend registry.

Architecture
------------
    MicroscopeConnector          Abstract base class â€” defines the contract.
    initialize_api()             Factory function â€” creates the right backend.
    register_backend()           Registers a manufacturer-specific connector class.

Usage
-----
    from microscope_connector import initialize_api

    # Connect to Leica LAS X (backend in lasx_connector.py)
    api = initialize_api("lasx", client_name="PythonClient")

    # Use the uniform interface
    if api.is_connected:
        hw = api.get_hardware_info()
        jobs = api.get_jobs_list()
        api.disconnect()

    # Context manager
    with initialize_api("lasx") as api:
        hw = api.get_hardware_info()

Extending
---------
    To add a new manufacturer, create a file (e.g. ``zen_connector.py``) that:
      1. Subclasses ``MicroscopeConnector``
      2. Implements all abstract methods
      3. Calls ``register_backend("zen", ZenConnector)``

    See ``lasx_connector.py`` for a reference implementation.

Metadata
--------
    Author:  Adaptive Feedback Microscopy project
    Version: 1.0.0
    License: MIT
    Python:  >= 3.9
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type


__all__ = [
    "MicroscopeConnector",
    "initialize_api",
    "register_backend",
    "list_backends",
]

__version__ = "1.0.0"


# â”€â”€â”€ Backend Registry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_BACKEND_REGISTRY: Dict[str, Type[MicroscopeConnector]] = {}


def register_backend(name: str, cls: Type[MicroscopeConnector]) -> None:
    """
    Register a manufacturer-specific connector class.

    Parameters
    ----------
    name : str
        Short identifier for the backend (e.g. ``"lasx"``, ``"zen"``).
        Stored lowercase for case-insensitive lookup.
    cls : type
        A subclass of :class:`MicroscopeConnector`.

    Raises
    ------
    TypeError
        If *cls* is not a subclass of :class:`MicroscopeConnector`.
    """
    if not (isinstance(cls, type) and issubclass(cls, MicroscopeConnector)):
        raise TypeError(
            f"Backend class must be a subclass of MicroscopeConnector, "
            f"got {cls!r}"
        )
    _BACKEND_REGISTRY[name.lower()] = cls


def list_backends() -> List[str]:
    """Return the names of all registered backends."""
    return sorted(_BACKEND_REGISTRY.keys())


# â”€â”€â”€ Abstract Base Class â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class MicroscopeConnector(ABC):
    """
    Abstract base class for microscope API connectors.

    Defines a uniform interface that all manufacturer-specific backends must
    implement.  Every method that talks to hardware returns ``None`` on failure
    rather than raising, so callers can degrade gracefully when the API is
    unavailable.

    Attributes
    ----------
    client_name : str
        Identifier passed to the microscope software on connection.
    timeout : float
        Default timeout in seconds for API operations.
    client : Any
        The underlying vendor-specific client object (or ``None``).

    Notes
    -----
    Thread safety: implementations should protect shared state with
    ``self._lock`` (a :class:`threading.Lock` created in ``__init__``).
    """

    def __init__(
        self,
        client_name: str = "PythonConnector",
        timeout: float = 15.0,
        **kwargs: Any,
    ) -> None:
        """
        Initialise the connector.

        Parameters
        ----------
        client_name : str
            Name shown in the microscope software's client list.
        timeout : float
            Default timeout (seconds) for API calls.
        **kwargs : Any
            Backend-specific options (e.g. ``password``, ``host``, ``port``).
        """
        self.client_name: str = client_name
        self.timeout: float = timeout
        self.client: Any = None
        self._lock: threading.Lock = threading.Lock()
        self._connected: bool = False
        self._owns_connection: bool = True

    # â”€â”€ Connection lifecycle â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @abstractmethod
    def connect(self) -> bool:
        """
        Open a connection to the microscope API.

        Returns
        -------
        bool
            ``True`` if the connection succeeded, ``False`` otherwise.
        """
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """
        Gracefully close the API connection.

        Only disconnects if this instance owns the connection
        (i.e. it was not created via :meth:`from_existing_client`).
        """
        ...

    @abstractmethod
    def ping(self) -> bool:
        """
        Check whether the API is responsive.

        Returns
        -------
        bool
            ``True`` if the API responds within the timeout.
        """
        ...

    @property
    def is_connected(self) -> bool:
        """``True`` if an active connection exists."""
        return self._connected

    @property
    def backend_name(self) -> str:
        """
        Short identifier for this backend (e.g. ``"lasx"``).

        Subclasses should override this with a class-level constant or
        property that returns a fixed string.
        """
        return "unknown"

    # â”€â”€ Generic command execution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @abstractmethod
    def execute_command(
        self,
        command: str,
        timeout: Optional[float] = None,
    ) -> bool:
        """
        Execute a named command on the microscope API.

        Parameters
        ----------
        command : str
            Vendor-specific command string.
        timeout : float, optional
            Override the default timeout for this call.

        Returns
        -------
        bool
            ``True`` if the command succeeded.
        """
        ...

    # â”€â”€ Hardware & job queries â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @abstractmethod
    def get_hardware_info(self) -> Optional[Dict[str, Any]]:
        """
        Query the microscope for hardware information.

        Returns
        -------
        dict or None
            A dictionary whose keys depend on the backend (e.g.
            ``SerialNumber``, ``SystemType``, ``Microscope``, ``Objectives``).
            Returns ``None`` if the query fails.
        """
        ...

    @abstractmethod
    def get_jobs_list(self) -> Optional[List[Dict[str, Any]]]:
        """
        List available acquisition jobs / experiments.

        Returns
        -------
        list[dict] or None
            Each dict contains at least ``"Name"`` (str).
            Additional keys (``"ID"``, ``"IsAutofocus"``, â€¦) are
            backend-specific.
        """
        ...

    @abstractmethod
    def get_job_settings(
        self,
        job_name: str,
        verbose: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch detailed settings for a single acquisition job.

        Parameters
        ----------
        job_name : str
            Name of the job as returned by :meth:`get_jobs_list`.
        verbose : bool
            If ``True``, print debug information.

        Returns
        -------
        dict or None
            Job-specific settings (pixel size, image size, zoom, â€¦).
        """
        ...

    # â”€â”€ Convenience â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def get_all_job_settings(self) -> Dict[str, Dict[str, Any]]:
        """
        Fetch settings for every available job.

        Returns
        -------
        dict[str, dict]
            Mapping of job name to its settings dict.
        """
        result: Dict[str, Dict[str, Any]] = {}
        jobs = self.get_jobs_list()
        if not jobs:
            return result
        for job in jobs:
            name = job.get("Name")
            if name:
                settings = self.get_job_settings(name)
                if settings:
                    result[name] = settings
        return result

    # â”€â”€ Wrapping an existing client â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @classmethod
    def from_existing_client(
        cls,
        client: Any,
        timeout: float = 15.0,
        **kwargs: Any,
    ) -> "MicroscopeConnector":
        """
        Create a connector that wraps an already-connected client object.

        The resulting instance will *not* call :meth:`disconnect` on cleanup
        because it does not own the connection.

        Parameters
        ----------
        client : Any
            A vendor-specific client that is already connected.
        timeout : float
            Timeout for subsequent operations.
        **kwargs : Any
            Additional backend-specific options.

        Returns
        -------
        MicroscopeConnector
            A ready-to-use connector instance.
        """
        instance = cls(timeout=timeout, **kwargs)
        instance.client = client
        instance._connected = True
        instance._owns_connection = False
        return instance

    # â”€â”€ Context manager â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def __enter__(self) -> "MicroscopeConnector":
        if not self._connected:
            self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.disconnect()
        return False

    # â”€â”€ Representation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        return (
            f"<{self.__class__.__name__} "
            f"backend={self.backend_name!r} "
            f"client_name={self.client_name!r} "
            f"status={status}>"
        )


# â”€â”€â”€ Factory Function â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def initialize_api(
    backend: str,
    client_name: str = "PythonClient",
    timeout: float = 15.0,
    auto_connect: bool = True,
    **kwargs: Any,
) -> MicroscopeConnector:
    """
    Create and (optionally) connect a microscope API connector.

    This is the main entry point.  It looks up the requested backend in the
    registry, instantiates it, and connects unless told otherwise.

    Parameters
    ----------
    backend : str
        Name of the backend to use (e.g. ``"lasx"``, ``"zen"``).
        Case-insensitive.
    client_name : str
        Identifier shown in the microscope software.
    timeout : float
        Default timeout in seconds.
    auto_connect : bool
        If ``True`` (default), call :meth:`connect` immediately.
    **kwargs : Any
        Passed through to the backend constructor.  Common options:

        - ``password`` (str): For APIs that require authentication.
        - ``host`` (str): For network-connected microscopes.
        - ``port`` (int): For network-connected microscopes.

    Returns
    -------
    MicroscopeConnector
        A ready-to-use connector (connected if *auto_connect* is True).

    Raises
    ------
    ValueError
        If the requested backend is not registered.
    RuntimeError
        If *auto_connect* is True and the connection fails.

    Examples
    --------
    >>> api = initialize_api("lasx", client_name="MyApp")
    >>> api.is_connected
    True

    >>> api = initialize_api("lasx", auto_connect=False)
    >>> api.connect()
    True
    """
    key = backend.lower()

    # Auto-import known backends on first use
    if key not in _BACKEND_REGISTRY:
        _try_auto_import(key)

    if key not in _BACKEND_REGISTRY:
        available = ", ".join(list_backends()) or "(none)"
        raise ValueError(
            f"Unknown microscope backend: {backend!r}. "
            f"Registered backends: {available}. "
            f"Make sure the backend module is importable "
            f"(e.g. 'pip install lasx-connector' or add it to your PYTHONPATH)."
        )

    connector_cls = _BACKEND_REGISTRY[key]
    connector = connector_cls(
        client_name=client_name,
        timeout=timeout,
        **kwargs,
    )

    if auto_connect:
        if not connector.connect():
            raise RuntimeError(
                f"Failed to connect to {backend!r} API. "
                f"Is the microscope software running and the API enabled?"
            )

    return connector


def _try_auto_import(backend_key: str) -> None:
    """
    Attempt to import a backend module by convention.

    Mapping:
        "lasx" -> vendors.lasx
        "zen"  -> vendors.zen
        etc.

    The vendor package's ``__init__.py`` is expected to import and
    register backend classes.
    """
    module_name = f"vendors.{backend_key}"
    try:
        __import__(module_name)
    except ImportError:
        pass


# â”€â”€â”€ CLI â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


if __name__ == "__main__":
    print("Microscope Connector Framework")
    print("=" * 50)
    print(f"Version: {__version__}")
    print(f"Registered backends: {list_backends() or '(none â€” import a backend first)'}")
    print()
    print("Usage:")
    print("  from microscope_connector import initialize_api")
    print('  api = initialize_api("lasx", client_name="PythonClient")')
    print()
    print("Available backend modules (import to register):")
    print("  lasx_connector   â€” Leica LAS X")
    print("  (more to come)   â€” Zeiss ZEN, Nikon NIS-Elements, ...")
