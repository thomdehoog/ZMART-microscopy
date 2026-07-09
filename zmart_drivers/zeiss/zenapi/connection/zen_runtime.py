"""
ZEN API runtime: wheel presence, TLS, metadata, and the vendor seams.
=====================================================================
This is the ZEN analog of the Leica driver's ``connection.lasx_runtime``. Where
Leica loaded .NET CAM assemblies, ZEN ships a pip-installable ``zen_api`` wheel
of generated grpclib stubs -- so this module is a wheel-presence check plus the
TLS/metadata/config plumbing the gateway needs, and it is the ONE place that
knows the concrete ``zen_api`` module paths, stub classes, and request-message
field names.

Everything that touches ``zen_api`` / ``grpclib`` is imported lazily inside a
function, so the driver imports cleanly (and its offline tests run) on a machine
without the wheel or a gateway. Offline tests inject fakes for both the stub
factory and the message provider, so nothing here is exercised without hardware.

    RISK (bench-verify): the module paths, stub class names, and request-message
    field names below are transcribed from the zeiss-microscopy/OAD examples,
    not the installed wheel. They are all confined to this file so a rename
    touches one place. See the driver README "Risks" section.

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


# =============================================================================
# config.ini -> connection parameters
# =============================================================================


def load_config(config_path: str | Path) -> dict:
    """Parse a ZEN API ``config.ini`` ``[api]`` section.

    Mirrors ``zen_api_utils.misc.initialize_zenapi``: reads host, port,
    cert_file (resolved relative to the config file), and control-token.
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
    """Build the mandatory client TLS context (CA pin, HTTP/2 ALPN).

    Matches ``zen_api_utils.misc.initialize_zenapi``: verify against the gateway
    CA .pem, require a valid cert, check hostname, and negotiate ``h2``.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=str(cert_file))
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    context.set_alpn_protocols(["h2"])
    return context


def build_metadata(control_token: str) -> list[tuple[str, str]]:
    """The gRPC metadata attached to every stub: the control-token header."""
    return [("control-token", control_token)]


def make_channel(host: str, port: int, ssl_context):
    """Construct a grpclib ``Channel`` (must be called ON the event loop thread)."""
    from grpclib.client import Channel  # lazy: only needed with a live gateway

    return Channel(host=host, port=port, ssl=ssl_context)


# =============================================================================
# Stub factory -- the concrete zen_api service stubs, one per subsystem
# =============================================================================

# key -> (module path, stub class name). Targets the light-microscopy (lm) API
# for device services and the acquisition v1beta API for experiments.
_STUB_REGISTRY = {
    "stage": ("zen_api.lm.hardware.v2", "StageServiceStub"),
    "focus": ("zen_api.lm.hardware.v2", "FocusServiceStub"),
    "objective": ("zen_api.lm.hardware.v2", "ObjectiveChangerServiceStub"),
    "experiment": ("zen_api.acquisition.v1beta", "ExperimentServiceStub"),
    "experiment_streaming": ("zen_api.acquisition.v1beta", "ExperimentStreamingServiceStub"),
}


def get_stub_class(key: str):
    """Return the ``zen_api`` stub class for a subsystem key (lazy import)."""
    module_path, class_name = _STUB_REGISTRY[key]
    module = import_module(module_path)
    return getattr(module, class_name)


def default_stub_factory(key: str, channel, metadata):
    """Real stub factory: construct the subsystem stub bound to channel+metadata."""
    return get_stub_class(key)(channel=channel, metadata=metadata)


# =============================================================================
# Message provider -- builds the request messages for each RPC
# =============================================================================


class RealMessages:
    """Builds ``zen_api`` request messages (the one place field names live).

    Offline tests substitute a fake with the same method names, so these
    imports never load without the wheel. Field names marked below are the
    bench-verify risk surface.
    """

    def _hw(self):
        return import_module("zen_api.lm.hardware.v2")

    def _acq(self):
        return import_module("zen_api.acquisition.v1beta")

    # --- stage (meters) ---
    def stage_get(self):
        return self._hw().StageServiceGetPositionRequest()

    def stage_move(self, x_m, y_m):
        return self._hw().StageServiceMoveToRequest(x=x_m, y=y_m)

    # --- focus (meters) ---
    def focus_get(self):
        return self._hw().FocusServiceGetPositionRequest()

    def focus_move(self, z_m):
        return self._hw().FocusServiceMoveToRequest(value=z_m)

    # --- objective (turret index) ---
    def objective_get(self):
        return self._hw().ObjectiveChangerServiceGetPositionRequest()

    def objective_move(self, index):
        return self._hw().ObjectiveChangerServiceMoveToRequest(position_index=index)

    def objectives_get(self):
        return self._hw().ObjectiveChangerServiceGetObjectivesRequest()

    # --- experiment / acquisition ---
    def experiment_load(self, name):
        return self._acq().ExperimentServiceLoadRequest(name)

    def run_snap(self, experiment_id):
        return self._acq().ExperimentServiceRunSnapRequest(experiment_id=experiment_id)

    def run_experiment(self, experiment_id, output_name):
        return self._acq().ExperimentServiceRunExperimentRequest(
            experiment_id=experiment_id, output_name=output_name
        )

    def status_subscribe(self, experiment_id):
        return self._acq().ExperimentServiceRegisterOnStatusChangedRequest(experiment_id)

    def image_output_path(self, output_name):
        return self._acq().ExperimentServiceGetImageOutputPathRequest(output_name=output_name)
