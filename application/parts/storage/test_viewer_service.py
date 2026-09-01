"""The Smart Viewer sources that reach the operator canvas."""

from __future__ import annotations

import application.parts.storage.viewer_service as service


def _config(*layers: dict) -> dict:
    return {"layers": [{"kind": "image", **layer} for layer in layers]}


def _empty_service(*, port: int | None = None) -> dict:
    return {
        "server": None,
        "thread": None,
        "port": port,
        "error": None,
        "sources": {},
        "opened": set(),
    }


def test_every_field_in_one_viewer_dataset_is_kept():
    answered = service._the_sources_in(
        _config(
            {
                "group": "overview",
                "sources": [
                    f"/data/0/overview_P{number:06d}.ome.zarr/|zarr3:" for number in range(4)
                ],
            }
        ),
        port=8848,
    )

    assert len(answered["overview"]) == 4
    assert all(
        one["url"].startswith("http://127.0.0.1:8848/data/0/") for one in answered["overview"]
    )


def test_only_the_newest_dataset_generation_is_kept():
    answered = service._the_sources_in(
        _config(
            {
                "group": "overview",
                "sources": [
                    "/data/0/overview_P000000.ome.zarr/|zarr3:",
                    "/data/0/overview_P000001.ome.zarr/|zarr3:",
                    "/data/2/overview_P000000.ome.zarr/|zarr3:",
                    "/data/2/overview_P000001.ome.zarr/|zarr3:",
                    "/data/2/overview_P000002.ome.zarr/|zarr3:",
                ],
            }
        ),
        port=8848,
    )

    assert len(answered["overview"]) == 3
    assert all("/data/2/" in one["url"] for one in answered["overview"])


def test_viewer_decorations_do_not_make_an_extra_acquisition():
    answered = service._the_sources_in(
        _config(
            {
                "group": "session-abc · overview.zmartview.zarr (2)",
                "sources": ["/data/2/overview.ome.zarr/|zarr3:"],
            },
            {
                "group": "focussing",
                "sources": ["/data/3/focussing.ome.zarr/|zarr3:"],
            },
        ),
        port=8848,
    )

    assert sorted(answered) == ["focussing", "overview"]


def test_status_reads_the_live_viewer_config_afresh(monkeypatch):
    before = dict(service._viewer)
    service._viewer.clear()
    service._viewer.update(_empty_service(port=8848))
    asked: list[tuple[int, str]] = []

    def read(port: int, route: str) -> dict:
        asked.append((port, route))
        return _config(
            {
                "group": "overview",
                "sources": [
                    f"/data/0/overview_P{number:06d}.ome.zarr/|zarr3:" for number in range(4)
                ],
            }
        )

    monkeypatch.setattr(service, "_read", read)
    try:
        state = service.status()
    finally:
        service._viewer.clear()
        service._viewer.update(before)

    assert asked == [(8848, "/api/config")]
    assert len(state["sources"]["overview"]) == 4


def test_status_keeps_the_last_picture_when_a_refresh_stumbles(monkeypatch):
    before = dict(service._viewer)
    service._viewer.clear()
    service._viewer.update(_empty_service(port=8848))
    service._viewer["sources"] = {
        "overview": [{"url": "http://127.0.0.1:8848/data/0/overview.ome.zarr/", "name": "overview"}]
    }

    def unavailable(port: int, route: str) -> dict:
        raise TimeoutError(f"{port}{route} did not answer")

    monkeypatch.setattr(service, "_read", unavailable)
    try:
        state = service.status()
    finally:
        service._viewer.clear()
        service._viewer.update(before)

    assert len(state["sources"]["overview"]) == 1
    assert "current picture could not be read" in state["error"]


def test_a_growing_folder_is_opened_once_and_then_only_announced(monkeypatch, tmp_path):
    before = dict(service._viewer)
    service._viewer.clear()
    service._viewer.update(_empty_service(port=8848))
    calls: list[tuple[str, dict]] = []

    def ask(port: int, route: str, payload: dict) -> dict:
        assert port == 8848
        calls.append((route, payload))
        if route == "/api/stores/open":
            return _config(
                {
                    "group": "overview",
                    "sources": ["/data/0/overview_P000000.ome.zarr/|zarr3:"],
                }
            )
        return {}

    monkeypatch.setattr(service, "_ask", ask)
    try:
        service.a_position_landed("overview", tmp_path)
        service.a_position_landed("overview", tmp_path)
    finally:
        service._viewer.clear()
        service._viewer.update(before)

    assert [route for route, _ in calls] == [
        "/api/stores/open",
        "/api/announce",
        "/api/announce",
    ]
    assert not any(route == "/api/stores/close" for route, _ in calls)
