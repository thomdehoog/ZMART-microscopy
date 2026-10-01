"""The primitives: one plain function for each thing MockScope Control can do.

Each primitive sends exactly one command to the vendor software and returns
plain values. A primitive does not retry, wait or check limits; those are the
jobs of the dispatchers above it. Keeping the primitives this simple means
that all the careful work happens in one place, the same for every
microscope.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# The mock driver is the one driver allowed to import from its testing
# folder: here, the pretend vendor software *is* the microscope. A real
# driver imports the vendor's own library at this point instead.
from ..testing.mock_api import MockScope, read_mraw


class VendorError(Exception):
    """The vendor software refused a command and answered with an error code.

    ``code`` is the vendor's number (see the MockScope error table) and
    ``message`` its text. The error handling sorts these into kinds; nothing
    else in the driver looks at the code.
    """

    def __init__(self, command: str, code: int, message: str) -> None:
        super().__init__(f"{command} refused by the microscope software: {message} (code {code})")
        self.command = command
        self.code = code
        self.message = message


class MockScopeConnection:
    """An open connection to MockScope Control.

    Create one with :meth:`start`. The underlying :class:`MockScope` is
    available as :attr:`scope`, so tests can make it misbehave on purpose.
    """

    def __init__(self, scope: MockScope) -> None:
        self.scope = scope

    @classmethod
    def start(
        cls, *, output_folder: Path, token: str, instant: bool = False
    ) -> MockScopeConnection:
        """Start the pretend vendor software and log in.

        ``output_folder`` is where the software writes its own raw files.
        ``instant=True`` makes every movement and acquisition finish at once,
        which is handy for quick tests; otherwise they take a realistic time.
        Raises ``RuntimeError`` when the login is refused. The message never
        contains the token itself.
        """
        output_folder.mkdir(parents=True, exist_ok=True)
        if instant:
            scope = MockScope.instant(output_folder=output_folder, token="mock-token")
        else:
            scope = MockScope(output_folder=output_folder, token="mock-token")
        connection = cls(scope)
        try:
            connection._call("Login", token=token)
        except VendorError as exc:
            scope.shutdown()
            raise RuntimeError(
                f"the microscope software refused the login ({exc.message}); "
                f"check the 'token' entry of the connection"
            ) from None
        return connection

    def _call(self, command: str, **arguments: Any) -> dict[str, Any]:
        """Send one command and return its result, or raise VendorError."""
        reply = self.scope.send(command, **arguments)
        if not reply["ok"]:
            raise VendorError(command, reply["code"], reply["message"])
        return reply["result"]

    # --- the session -----------------------------------------------------

    def version(self) -> dict[str, str]:
        """``{"software", "version"}`` of the vendor software."""
        return dict(self._call("GetVersion"))

    def close(self) -> None:
        """Log out and close the vendor software. Safe to call twice."""
        try:
            self._call("Logout")
        except (VendorError, ConnectionError):
            pass
        self.scope.shutdown()

    # --- reading ---------------------------------------------------------

    def hardware(self) -> dict[str, Any]:
        """Serial number, travel ranges, objectives, camera and setting ranges."""
        return self._call("GetHardware")

    def stage_position(self) -> dict[str, float]:
        """The stage position, ``{"x", "y"}``, in raw stage micrometers."""
        result = self._call("GetStagePosition")
        return {"x": float(result["x"]), "y": float(result["y"])}

    def focus_position(self) -> dict[str, float]:
        """The two focus drives, ``{"focus", "piezo"}``, in raw micrometers."""
        result = self._call("GetFocus")
        return {"focus": float(result["focus"]), "piezo": float(result["piezo"])}

    def settings(self) -> dict[str, Any]:
        """The vendor's settings, by the vendor's own names, plus the objective slot."""
        return dict(self._call("GetSettings"))

    def status(self) -> dict[str, Any]:
        """What the software is doing now, and the state of the last acquisition."""
        return self._call("GetStatus")

    def read_image_file(self, path: str | Path) -> tuple[dict[str, Any], list]:
        """Read one of the vendor's ``.mraw`` files: ``(description, planes)``.

        Raises ``ValueError`` while the file is still incomplete.
        """
        return read_mraw(path)

    # --- changing --------------------------------------------------------

    def move_stage(self, *, x: float, y: float) -> None:
        """Start a stage move to raw position x, y. Returns when accepted, not when arrived."""
        self._call("MoveStage", x=x, y=y)

    def move_focus(self, *, focus: float, piezo: float) -> None:
        """Start a move of both focus drives. Returns when accepted, not when arrived."""
        self._call("MoveFocus", focus=focus, piezo=piezo)

    def set_setting(self, name: str, value: float) -> None:
        """Change one vendor setting, by the vendor's own name."""
        self._call("SetSetting", name=name, value=value)

    def set_objective(self, slot: int) -> None:
        """Start an objective change. Returns when accepted, not when finished."""
        self._call("SetObjective", slot=slot)

    def start_acquisition(self, name: str, *, z_planes: int, z_step_um: float) -> str | None:
        """Start an acquisition and return the path of the file it will write.

        Returns ``None`` if the software accepted the command without naming
        a file, which happens when it quietly ignored it.
        """
        result = self._call("StartAcquisition", name=name, z_planes=z_planes, z_step_um=z_step_um)
        return result.get("file")

    def abort(self) -> None:
        """Stop every movement and any running acquisition."""
        self._call("Abort")
