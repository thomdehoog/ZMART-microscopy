"""The macro installer writes macros with this machine's path and the chosen port."""

from pathlib import Path

from nis_elements_6_10.bridge import install


def test_render_doubles_backslashes_and_carries_port():
    start, stop = install.render(
        Path(r"C:\repo\zmart_drivers\nikon"), Path(r"C:\repo\b.stop"), 5000
    )
    assert r"p = r'C:\\repo\\zmart_drivers\\nikon'" in start
    assert 'ExistFile("C:\\\\repo\\\\b.stop")' in start
    assert "b.start(port=5000)" in start and "port 5000" in start
    assert r"open(r'C:\\repo\\b.stop', 'w')" in stop
    # nothing NIS silently chokes on: no comment lines, no string variables
    assert not any(line.startswith("//") or line.startswith("char ") for line in start.splitlines())


def test_install_writes_both_macros(tmp_path):
    start_path, stop_path = install.install(tmp_path, port=6000)
    assert start_path.exists() and stop_path.exists()
    raw = start_path.read_bytes()
    assert b"\r\n" in raw and b"\r\r\n" not in raw
    text = raw.decode("utf-8")
    assert "nis_elements_6_10.bridge.nis_bridge" in text
    # the path baked in is the real drivers/nikon folder of this checkout
    assert install._mac_literal(install.DRIVERS_NIKON_DIR) in text
