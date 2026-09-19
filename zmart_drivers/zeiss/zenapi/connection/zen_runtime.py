"""
ZEN API runtime: the one place that knows the real ``zen_api`` package.
=======================================================================
The ZEN API is a set of gRPC services. ZEISS ships the Python classes for
them as a ``zen_api`` wheel (generated with betterproto), and this module is
the only file in the driver that imports from that wheel. Everything else
talks in plain Python values, so if ZEISS renames a service or a field, the
fix lands here and nowhere else.

What lives here:

* ``load_config``, ``build_ssl_context``, ``build_metadata``, ``make_channel``
  -- turning a ``config.ini`` into a TLS connection with the control token
  attached (the same steps ZEISS's own ``initialize_zenapi`` example takes).
* ``get_stub_class`` -- picks the right service class for each subsystem.
  The stage service moved between ZEN releases (see ``_STUB_REGISTRY``), so a
  subsystem can list several candidates and the first one the installed wheel
  provides is used.
* ``RealMessages`` -- builds the request objects for every call the driver
  makes, with the field names of the real wheel.

Everything that touches ``zen_api`` or ``grpclib`` is imported lazily inside a
function, so the driver imports cleanly on a machine without the wheel and the
offline tests can run there. The tests under ``tests/gateway`` exercise this
module for real against the fake gateway in ``zenapi.simulator``.

Verified against the ``zen_api`` wheels ZEISS publishes in the OAD repository:
2025.10.1 (ZEN 3.13) and 2026.05.1 (ZEN 3.14).

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import configparser
import ssl
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path


def zen_api_available() -> bool:
    """True if the ``zen_api`` wheel is importable in this environment."""
    return find_spec("zen_api") is not None


def grpclib_available() -> bool:
    """True if ``grpclib`` (the async gRPC transport) is importable."""
    return find_spec("grpclib") is not None


def zen_api_version() -> str | None:
    """The installed ``zen_api`` wheel version (``"2026.5.1"``), or None."""
    try:
        from importlib.metadata import version

        return version("zen_api")
    except Exception:  # noqa: BLE001 - version is informational only
        return None


# =============================================================================
# config.ini -> connection parameters
# =============================================================================


def load_config(config_path: str | Path) -> dict:
    """Read the ``[api]`` section of a ZEN API ``config.ini``.

    The file has the same shape ZEISS uses in its Python examples::

        [api]
        host = 127.0.0.1
        port = 5002
        cert_file = C:\\ProgramData\\Carl Zeiss\\ZEN APIGateway\\Certificates\\ZEN APIPersonalSigningRootCA.pem
        control-token = <the global control token of the gateway>

    A relative ``cert_file`` is resolved next to the config file. Returns a
    dict with ``host``, ``port``, ``cert_file`` and ``control_token``.
    Raises ``FileNotFoundError`` when the file does not exist.
    """
    path = Path(config_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"ZEN API config not found: {path}")
    parser = configparser.ConfigParser()
    parser.read(path)
    api = parser["api"]
    cert_file = Path(api["cert_file"])
    if not cert_file.is_absolute():
        cert_file = (path.parent / cert_file).resolve()
    return {
        "host": api.get("host", "127.0.0.1"),
        "port": int(api.get("port", "5002")),
        "cert_file": str(cert_file),
        "control_token": api.get("control-token", api.get("control_token", "")),
    }


def build_ssl_context(cert_file: str | Path) -> ssl.SSLContext:
    """Build the client TLS context the gateway requires.

    The gateway only talks over TLS. We verify its certificate against the
    root certificate ZEISS's gateway generated (the ``.pem`` in ``cert_file``),
    check the host name, and ask for HTTP/2 -- exactly what ZEISS's
    ``initialize_zenapi`` example does.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=str(cert_file))
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    context.set_alpn_protocols(["h2"])
    return context


def build_metadata(control_token: str) -> list[tuple[str, str]]:
    """The gRPC metadata sent with every call: the ``control-token`` header.

    The gateway refuses any call that does not carry its global control
    token, so every service stub is created with this metadata attached.
    """
    return [("control-token", control_token)]


def make_channel(host: str, port: int, ssl_context):
    """Construct a grpclib ``Channel`` (must be called ON the event loop thread)."""
    from grpclib.client import Channel  # lazy: only needed with a live gateway

    return Channel(host=host, port=port, ssl=ssl_context)


# =============================================================================
# Service classes -- one per subsystem, with fallbacks across ZEN releases
# =============================================================================

# subsystem key -> candidates of (module path, stub class name), tried in order.
#
# The XY stage service moved between releases: the 2025.10.1 wheel (ZEN 3.13)
# has ``zen_api.lm.hardware.v2.StageService``; the 2026.05.1 wheel (ZEN 3.14)
# dropped it and offers ``zen_api.hardware.v1.SimpleStageService`` instead.
# Both have the same two calls we use (GetPosition -> x, y in meters; MoveTo
# with x, y in meters), so the driver simply takes the first one the installed
# wheel provides. Focus, objective changer and experiments did not move.
_STUB_REGISTRY: dict[str, list[tuple[str, str]]] = {
    "stage": [
        ("zen_api.hardware.v1", "SimpleStageServiceStub"),
        ("zen_api.lm.hardware.v2", "StageServiceStub"),
    ],
    "focus": [("zen_api.lm.hardware.v2", "FocusServiceStub")],
    "objective": [("zen_api.lm.hardware.v2", "ObjectiveChangerServiceStub")],
    "experiment": [("zen_api.acquisition.v1beta", "ExperimentServiceStub")],
    "experiment_streaming": [("zen_api.acquisition.v1beta", "ExperimentStreamingServiceStub")],
    "sw_autofocus": [("zen_api.lm.acquisition.v1", "ExperimentSwAutofocusServiceStub")],
    "definite_focus": [("zen_api.lm.acquisition.v1", "DefiniteFocusServiceStub")],
}


def _resolve(key: str) -> tuple[str, str]:
    """Return the (module path, class name) the installed wheel provides for ``key``."""
    tried = []
    for module_path, class_name in _STUB_REGISTRY[key]:
        tried.append(f"{module_path}.{class_name}")
        try:
            module = import_module(module_path)
        except ImportError:
            continue
        if hasattr(module, class_name):
            return module_path, class_name
    raise ImportError(
        f"The installed zen_api wheel provides none of the known {key!r} services "
        f"(tried {', '.join(tried)}). Check the wheel version against the driver README."
    )


def get_stub_class(key: str):
    """Return the ``zen_api`` stub class for a subsystem key (lazy import)."""
    module_path, class_name = _resolve(key)
    return getattr(import_module(module_path), class_name)


def default_stub_factory(key: str, channel, metadata):
    """Real stub factory: construct the subsystem stub bound to channel+metadata."""
    return get_stub_class(key)(channel=channel, metadata=metadata)


def describe_runtime() -> dict:
    """What this machine has: the wheel version and which service each key resolved to.

    Used by ``get_info`` so a bench log records exactly which API surface the
    session spoke. Missing services are reported, not raised.
    """
    services = {}
    for key in _STUB_REGISTRY:
        try:
            module_path, class_name = _resolve(key)
            services[key] = f"{module_path}.{class_name}"
        except ImportError as exc:
            services[key] = f"unavailable ({exc})"
    return {
        "zen_api_version": zen_api_version(),
        "grpclib_available": grpclib_available(),
        "services": services,
    }


# =============================================================================
# Request messages -- the field names of the real wheel live here
# =============================================================================


class RealMessages:
    """Builds ``zen_api`` request messages (the one place field names live).

    Offline tests substitute a fake with the same method names, so these
    imports never load without the wheel. Distances are in meters on the
    wire; callers convert from micrometers before calling these builders.
    """

    def _stage(self):
        module_path, _ = _resolve("stage")
        return import_module(module_path)

    def _stage_prefix(self) -> str:
        # "SimpleStageService" (hardware.v1) or "StageService" (lm.hardware.v2)
        _, class_name = _resolve("stage")
        return class_name[: -len("Stub")]

    def _hw(self):
        return import_module("zen_api.lm.hardware.v2")

    def _acq(self):
        return import_module("zen_api.acquisition.v1beta")

    def _lm_acq(self):
        return import_module("zen_api.lm.acquisition.v1")

    # --- stage (meters) ---
    def stage_get(self):
        return getattr(self._stage(), f"{self._stage_prefix()}GetPositionRequest")()

    def stage_move(self, x_m, y_m):
        # x and y are optional on the wire ("leave out to keep that axis");
        # the driver always sends both.
        return getattr(self._stage(), f"{self._stage_prefix()}MoveToRequest")(x=x_m, y=y_m)

    # --- focus (meters) ---
    def focus_get(self):
        return self._hw().FocusServiceGetPositionRequest()

    def focus_move(self, z_m):
        return self._hw().FocusServiceMoveToRequest(value=z_m)

    # --- objective changer (position index) ---
    def objective_get(self):
        return self._hw().ObjectiveChangerServiceGetPositionRequest()

    def objective_move(self, index):
        return self._hw().ObjectiveChangerServiceMoveToRequest(position_index=index)

    def objectives_get(self):
        return self._hw().ObjectiveChangerServiceGetObjectivesRequest()

    # --- experiments (acquisition.v1beta) ---
    def experiments_available(self):
        return self._acq().ExperimentServiceGetAvailableExperimentsRequest()

    def experiment_load(self, name):
        return self._acq().ExperimentServiceLoadRequest(experiment_name=name)

    def run_snap(self, experiment_id, output_name=""):
        return self._acq().ExperimentServiceRunSnapRequest(
            experiment_id=experiment_id, output_name=output_name or ""
        )

    def run_experiment(self, experiment_id, output_name=""):
        return self._acq().ExperimentServiceRunExperimentRequest(
            experiment_id=experiment_id, output_name=output_name or ""
        )

    def start_experiment(self, experiment_id, output_name=""):
        return self._acq().ExperimentServiceStartExperimentRequest(
            experiment_id=experiment_id, output_name=output_name or ""
        )

    def start_live(self, experiment_id):
        return self._acq().ExperimentServiceStartLiveRequest(experiment_id=experiment_id)

    def stop(self, experiment_id=""):
        return self._acq().ExperimentServiceStopRequest(experiment_id=experiment_id or "")

    def status_get(self, experiment_id=""):
        return self._acq().ExperimentServiceGetStatusRequest(experiment_id=experiment_id or "")

    def status_subscribe(self, experiment_id=""):
        return self._acq().ExperimentServiceRegisterOnStatusChangedRequest(
            experiment_id=experiment_id or ""
        )

    def image_output_path(self):
        # Takes no arguments: ZEN reports the folder where it writes CZI files.
        return self._acq().ExperimentServiceGetImageOutputPathRequest()

    # --- focus helpers (lm.acquisition.v1) ---
    def find_autofocus(self, experiment_id, timeout_s=None):
        return self._lm_acq().ExperimentSwAutofocusServiceFindAutoFocusRequest(
            experiment_id=experiment_id, timeout=timeout_s
        )

    def find_surface(self):
        return self._lm_acq().DefiniteFocusServiceFindSurfaceRequest()

    def store_focus(self):
        return self._lm_acq().DefiniteFocusServiceStoreFocusRequest()

    def recall_focus(self):
        return self._lm_acq().DefiniteFocusServiceRecallFocusRequest()
