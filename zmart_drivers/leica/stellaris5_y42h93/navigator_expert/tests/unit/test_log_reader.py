"""
Unit tests for readers.log_reader (offline, no driver, no hardware).
=================================================================
Fixtures are synthetic log lines. Covers the failure modes that matter:
latin-1/µ decoding, <LF>/<TAB> tokens, partial/malformed lines, blank
imageSize (skip), duplicate job names within the current window (fail
closed), session block-id reassignment (use latest), per-job + global
staleness exposure and max_age_s refusal, ambiguous/nonnumeric selection,
hardware-info parsing, missing log, scan-status mapping, and modal-dialog
detection by line order.

    python -m pytest test_log_reader.py
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from navigator_expert.config import profiles
from navigator_expert.readers import log_reader as L

BASE = datetime(2026, 5, 28, 20, 0, 0)
NOWE = (BASE + timedelta(seconds=5)).timestamp()
NONE_PATH = os.path.join(tempfile.gettempdir(), "__no_such_msgbox__.log")


def ts(offset_s=0):
    return (BASE + timedelta(seconds=offset_s)).strftime("%Y-%m-%d %H:%M:%S.%f")


def _atl_obj(block_id, name, image="1.16 mm x 1.16 mm", zoom=1.0, zwide=1810.7):
    return {
        "id": block_id,
        "jobName": name,
        "imageSize": image,
        "pixelSize": "1.13 um x 1.13 um",
        "format": "1024 x 1024",
        "zoom": {"current": zoom},
        "scanSpeed": {"value": 400, "isResonant": False},
        "activeSettings": [
            {"pinholeAiry": {"value": 1.0}, "activeDetectors": [], "activeLaserLines": []}
        ],
        "zPosition": {"z-wide": {"position": zwide}, "z-galvo": {"position": 0.0}},
        "objective": {"name": "10x", "slotIndex": 0},
    }


def atl_line(offset, block_id, name, **kw):
    return (
        f"{ts(offset)} NavigatorExpert 'Result of command ATL "
        f'ATL_GetBlockApiInfoAsJsonString \'<Result Error="">'
        f"{json.dumps(_atl_obj(block_id, name, **kw))}''"
    )


def xy_line(offset, x, y):
    return (
        f"{ts(offset)} Result of command Scanner GetStageHwPosition "
        f'\'<Result HwStagePosX="{x}" HwStagePosY="{y}" Unit="m"/>\''
    )


def sel_line(offset, element):
    return (
        f'{ts(offset)} NavigatorExpert \'Command <ATL Command="ATL_Sequence" '
        f'BlockIDOfSequence="160" SubCommand="SetCurrentSelectedElementID" '
        f'ElementID="{element}" Origin="NavigatorExpert"/>\''
    )


def matrix_jobs_line(offset):
    return (
        f"{ts(offset)} Result of command Scanner GetMatrixCollectionPatternInfo "
        '\'<Result IsValidRequest="1">'
        "<Block><BlockId>4</BlockId><BlockType>1</BlockType>"
        "<BlockName>AF Job</BlockName><ContainsCameraSetting>0</ContainsCameraSetting>"
        "<ContainsWizardJob>0</ContainsWizardJob><IsAutoFocusOnStart>1</IsAutoFocusOnStart>"
        "<AutoFocusConfig><Range>0.000080</Range><AutoFocusUseFixSliceNumber>1</AutoFocusUseFixSliceNumber>"
        "<AutoFocusFixSliceCount>87</AutoFocusFixSliceCount></AutoFocusConfig>"
        "<ScanMode>xyz</ScanMode></Block>"
        "<Block><BlockId>6</BlockId><BlockType>1</BlockType>"
        "<BlockName>Overview</BlockName><ContainsCameraSetting>0</ContainsCameraSetting>"
        "<ContainsWizardJob>0</ContainsWizardJob><IsAutoFocusOnStart>0</IsAutoFocusOnStart>"
        "<ScanMode>xyz</ScanMode></Block>"
        "<Block><BlockId>8</BlockId><BlockType>1</BlockType>"
        "<BlockName>HiRes</BlockName><ContainsCameraSetting>0</ContainsCameraSetting>"
        "<ContainsWizardJob>0</ContainsWizardJob><IsAutoFocusOnStart>0</IsAutoFocusOnStart>"
        "<ScanMode>xyz</ScanMode></Block>"
        "</Result>'"
    )


def current_block_lines(offset, name, block_id):
    return [
        f"{ts(offset)} 0001 Info LCSCom.Tree.Root.Acquire.ATL.CurrentBlock "
        f"'Entry(822) CurrentBlock/Name = {name} '",
        f"{ts(offset)} 0001 Info LCSCom.Tree.Root.Acquire.ATL.CurrentBlock "
        f"'Entry(823) CurrentBlock/BlockID = {block_id} '",
    ]


def hw_line(offset):
    return (
        f"{ts(offset)} Result of command Scanner GetConfocalHardwareInfoAsJson "
        f"'<Result Error=\"\">{json.dumps({'Microscope': {'name': 'DM Manual-6'}})}''"
    )


def parse(lines, now=NOWE):
    return L.parse_log(lines=lines, msgbox_path=NONE_PATH, now=now)


class TestLogReader(unittest.TestCase):
    def test_basic_readers(self):
        s = parse([xy_line(0, "0.0634", "0.0360"), atl_line(1, 224, "AF Job")])
        self.assertEqual(L.get_xy(s)["x_um"], 63400.0)
        self.assertIsNotNone(L.get_job_settings("AF Job", s))
        self.assertIsNotNone(L.get_fov("AF Job", s))
        self.assertAlmostEqual(L.read_zwide_um("AF Job", s), 1810.7, places=1)

    def test_lf_tab_tokens_decoded(self):
        obj = json.dumps(_atl_obj(224, "AF Job")).replace(", ", ",<LF>")
        line = (
            f"{ts(0)} Result of command ATL ATL_GetBlockApiInfoAsJsonString "
            f"'<Result Error=\"\">{obj}''"
        )
        s = parse([line])
        self.assertIsNotNone(L.get_job_settings("AF Job", s))

    def test_blank_imagesize_skipped(self):
        s = parse(
            [
                atl_line(0, 224, "AF Job", image="1.16 mm x 1.16 mm"),
                atl_line(1, 224, "AF Job", image=""),
            ]
        )
        self.assertEqual(L.get_job_settings("AF Job", s)["imageSize"], "1.16 mm x 1.16 mm")

    def test_duplicate_names_within_window_fail_closed(self):
        s = parse([atl_line(0, 10, "Dup"), atl_line(1, 11, "Dup")])
        self.assertIsNone(L.get_job_settings("Dup", s))
        jobs = {j["Name"]: j for j in L.get_jobs(s)}
        self.assertIsNone(jobs["Dup"]["IsSelected"])

    def test_duplicate_far_apart_but_both_current_fail_closed(self):
        # 60s apart but both within current_window (180s) -> still ambiguous
        s = parse(
            [atl_line(0, 10, "Dup"), atl_line(60, 11, "Dup")],
            now=(BASE + timedelta(seconds=65)).timestamp(),
        )
        self.assertIsNone(L.get_job_settings("Dup", s))

    def test_session_reassignment_uses_latest(self):
        # same name, ids hours apart -> old session block excluded, use latest
        s = parse(
            [atl_line(0, 224, "Job", zoom=1.0), atl_line(3600, 238, "Job", zoom=4.0)],
            now=(BASE + timedelta(seconds=3605)).timestamp(),
        )
        js = L.get_job_settings("Job", s)
        self.assertIsNotNone(js)
        self.assertEqual(js["id"], 238)

    def test_valid_selection(self):
        s = parse(
            [atl_line(0, 10, "A"), atl_line(0, 11, "B"), atl_line(0, 12, "C"), sel_line(1, 2)]
        )
        self.assertEqual([j["Name"] for j in L.get_jobs(s) if j["IsSelected"]], ["B"])

    def test_matrix_collection_pattern_info_supplies_full_job_list(self):
        s = parse([matrix_jobs_line(0), atl_line(1, 6, "Overview"), sel_line(2, 2)])
        jobs = L.get_jobs(s)
        self.assertEqual([j["Name"] for j in jobs], ["AF Job", "Overview", "HiRes"])
        self.assertEqual([j["Name"] for j in jobs if j["IsSelected"]], ["Overview"])
        self.assertTrue(jobs[0]["IsAutofocus"])
        self.assertEqual(jobs[0]["FocusSliceCount"], 87)
        self.assertIsNotNone(L.get_job_settings("Overview", s))
        self.assertIsNone(L.get_job_settings("AF Job", s))

    def test_new_block_name_drops_stale_block_id(self):
        # A fresh Name line without its BlockID (writer race / partial dump)
        # must not pair with the previous generation's ID.
        lines = current_block_lines(2, "Overview", 6) + [
            current_block_lines(3, "Target", 9)[0]  # Name only, no BlockID line
        ]
        msgbox = self._write_msgbox(lines)
        s = L.parse_log(
            lines=[],
            msgbox_path=msgbox,
            now=(BASE + timedelta(seconds=5)).timestamp(),
        )
        self.assertEqual(s.current_block_name, "Target")
        self.assertIsNone(s.current_block_id)  # not the stale 6

    def test_matrix_job_list_honors_max_age(self):
        s = parse([matrix_jobs_line(0)], now=(BASE + timedelta(seconds=600)).timestamp())
        self.assertIsNotNone(L.get_jobs(s))
        self.assertIsNone(L.get_jobs(s, max_age_s=60.0))

    def test_current_block_can_mark_matrix_job_selection(self):
        msgbox = self._write_msgbox(current_block_lines(2, "Overview", 6))
        s = L.parse_log(
            lines=[matrix_jobs_line(0)],
            msgbox_path=msgbox,
            now=(BASE + timedelta(seconds=5)).timestamp(),
        )
        self.assertEqual(
            [j["Name"] for j in L.get_jobs(s) if j["IsSelected"]],
            ["Overview"],
        )

    def test_current_block_takes_precedence_over_selected_element_command(self):
        msgbox = self._write_msgbox(current_block_lines(3, "Overview", 6))
        s = L.parse_log(
            lines=[matrix_jobs_line(0), sel_line(2, 3)],
            msgbox_path=msgbox,
            now=(BASE + timedelta(seconds=5)).timestamp(),
        )
        self.assertEqual(
            [j["Name"] for j in L.get_jobs(s) if j["IsSelected"]],
            ["Overview"],
        )

    def test_selected_job_uses_fresh_current_block_when_job_list_is_stale(self):
        msgbox = self._write_msgbox(current_block_lines(120, "Overview", 6))
        s = L.parse_log(
            lines=[matrix_jobs_line(0)],
            msgbox_path=msgbox,
            now=(BASE + timedelta(seconds=125)).timestamp(),
        )
        self.assertIsNone(L.get_jobs(s, max_age_s=30.0))
        self.assertEqual(
            L.get_selected_job(s, max_age_s=30.0),
            {"Name": "Overview", "IsSelected": True, "ID": 6},
        )

    def test_selected_job_current_block_honors_max_age(self):
        msgbox = self._write_msgbox(current_block_lines(30, "Overview", 6))
        s = L.parse_log(
            lines=[],
            msgbox_path=msgbox,
            now=(BASE + timedelta(seconds=125)).timestamp(),
        )
        self.assertIsNone(L.get_selected_job(s, max_age_s=30.0))

    def test_ambiguous_selection_unknown(self):
        s = parse(
            [atl_line(0, 10, "A"), atl_line(0, 11, "B"), atl_line(0, 12, "C"), sel_line(1, 9)]
        )
        for j in L.get_jobs(s):
            self.assertIsNone(j["IsSelected"])

    def test_nonnumeric_block_id_fails_closed_not_crash(self):
        s = parse([atl_line(0, "abc", "A"), atl_line(0, 11, "B"), sel_line(1, 1)])
        jobs = L.get_jobs(s)  # must not raise
        self.assertIsNotNone(jobs)
        for j in jobs:
            self.assertIsNone(j["IsSelected"])  # unmappable -> unknown

    def test_partial_final_line_tolerated(self):
        truncated = atl_line(1, 224, "AF Job")[:-15]
        s = parse([xy_line(0, "0.06", "0.03"), truncated])
        self.assertIsNotNone(L.get_xy(s))

    def test_per_job_age_exposed(self):
        s = parse([atl_line(0, 224, "AF Job")], now=(BASE + timedelta(seconds=120)).timestamp())
        self.assertAlmostEqual(L.ages(s)["jobs"]["AF Job"], 120, delta=1)

    def test_stale_exposed_and_refused(self):
        s = parse(
            [xy_line(0, "0.06", "0.03"), atl_line(0, 224, "AF Job")],
            now=(BASE + timedelta(seconds=600)).timestamp(),
        )
        self.assertGreater(L.ages(s)["xy"], 500)
        self.assertGreater(L.ages(s)["jobs"]["AF Job"], 500)
        self.assertIsNotNone(L.get_xy(s))  # default: exposed, not refused
        old = profiles.LOG_READER
        try:
            profiles.LOG_READER = profiles.LogReaderProfile(max_age_s=60.0)
            self.assertIsNone(L.get_xy(s))
            self.assertIsNone(L.get_job_settings("AF Job", s))
            self.assertEqual(
                L.get_scan_status(
                    L.Snapshot(
                        scan_state=0,
                        scan_ts=BASE.timestamp(),
                        now=(BASE + timedelta(seconds=600)).timestamp(),
                    )
                ),
                "Unknown",
            )
        finally:
            profiles.LOG_READER = old

    def test_max_age_gates_get_jobs_and_selection(self):
        s = parse(
            [atl_line(0, 10, "A"), sel_line(1, 1)], now=(BASE + timedelta(seconds=600)).timestamp()
        )
        self.assertIsNotNone(L.get_jobs(s))  # default: exposed
        old = profiles.LOG_READER
        try:
            profiles.LOG_READER = profiles.LogReaderProfile(max_age_s=60.0)
            self.assertIsNone(L.get_jobs(s))  # stale blocks dropped
            self.assertIsNone(L.get_selected_job(s))
        finally:
            profiles.LOG_READER = old

    def test_missing_timestamp_is_stale_under_policy(self):
        bad = (
            "BADTS NavigatorExpert 'Result of command ATL "
            'ATL_GetBlockApiInfoAsJsonString \'<Result Error="">'
            f"{json.dumps(_atl_obj(10, 'A'))}''"
        )
        s = parse([bad])
        self.assertIsNotNone(L.get_job_settings("A", s))  # max_age None -> exposed
        old = profiles.LOG_READER
        try:
            profiles.LOG_READER = profiles.LogReaderProfile(max_age_s=60.0)
            self.assertIsNone(L.get_job_settings("A", s))  # no timestamp -> refused under policy
        finally:
            profiles.LOG_READER = old

    def test_missing_log_returns_none(self):
        s = L.parse_log(lcs_path=NONE_PATH, msgbox_path=NONE_PATH, now=NOWE)
        self.assertIsNone(L.get_xy(s))
        self.assertIsNone(L.get_jobs(s))
        self.assertIsNone(L.get_job_settings("AF Job", s))

    def test_hardware_info_parsed(self):
        s = parse([hw_line(0)])
        hw = L.get_hardware_info(s)
        self.assertIsNotNone(hw)
        self.assertEqual(hw["Microscope"]["name"], "DM Manual-6")

    def test_latin1_micro_in_imagesize(self):
        line = atl_line(0, 242, "HiRes", image="290.63 µm x 290.63 µm")
        fd, path = tempfile.mkstemp(suffix=".log")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write((line + "\n").encode("latin-1"))
            s = L.parse_log(lcs_path=path, msgbox_path=NONE_PATH, now=NOWE)
            fov = L.get_fov("HiRes", s)
            self.assertIsNotNone(fov)
            self.assertAlmostEqual(fov[0] * 1e6, 290.63, places=1)
        finally:
            os.remove(path)

    def test_scan_status_mapping(self):
        self.assertEqual(L.get_scan_status(L.Snapshot(scan_state=0)), "eScanIdle")
        self.assertEqual(L.get_scan_status(L.Snapshot(scan_state=4)), "eScanRunning")
        self.assertEqual(L.get_scan_status(L.Snapshot(scan_state=None)), "Unknown")

    def _write_msgbox(self, lines):
        fd, path = tempfile.mkstemp(suffix=".log")
        with os.fdopen(fd, "w", encoding="latin-1") as f:
            f.write("\n".join(lines) + "\n")
        self.addCleanup(os.remove, path)
        return path

    def test_dialog_open_then_closed_by_line_order(self):
        opn = f"{ts(0)} 0001 Info DbTracer 'MessageBox : Please turn turret manually.'"
        res = f"{ts(0)} 0001 Info DbTracer 'MessageBox Result: OK'"  # SAME timestamp
        # open then close (same ts) -> closed
        s = L.parse_log(lcs_path=NONE_PATH, msgbox_path=self._write_msgbox([opn, res]), now=NOWE)
        self.assertIsNone(L.get_pending_dialog(s))
        # close then open (same ts) -> open  (line order decides, not timestamp)
        s2 = L.parse_log(lcs_path=NONE_PATH, msgbox_path=self._write_msgbox([res, opn]), now=NOWE)
        self.assertIn("turn turret", (L.get_pending_dialog(s2) or ""))

    def test_dialog_interleaved_latest_open_wins(self):
        a = f"{ts(0)} 0001 Info DbTracer 'MessageBox : Dialog A'"
        ok = f"{ts(1)} 0001 Info DbTracer 'MessageBox Result: OK'"
        b = f"{ts(2)} 0001 Info DbTracer 'MessageBox : Dialog B'"
        s = L.parse_log(lcs_path=NONE_PATH, msgbox_path=self._write_msgbox([a, ok, b]), now=NOWE)
        self.assertIn("Dialog B", (L.get_pending_dialog(s) or ""))

    def test_selection_partial_cluster_fails_closed(self):
        # A,C dumped long ago (aged out), only B current; selected element 1
        # refers to the FULL A/B/C sequence -> must NOT map onto the {B} cluster.
        s = parse(
            [
                atl_line(0, 10, "A"),
                atl_line(0, 12, "C"),
                atl_line(3600, 11, "B"),
                sel_line(3601, 1),
            ],
            now=(BASE + timedelta(seconds=3605)).timestamp(),
        )
        jobs = {j["Name"]: j for j in L.get_jobs(s)}
        self.assertEqual(set(jobs), {"B"})  # only B is current
        self.assertIsNone(jobs["B"]["IsSelected"])  # partial -> selection unknown
        self.assertIsNone(L.get_selected_job(s))

    def test_dialog_age_exposed(self):
        opn = f"{ts(0)} 0001 Info DbTracer 'MessageBox : Please turn turret manually.'"
        s = L.parse_log(
            lcs_path=NONE_PATH,
            msgbox_path=self._write_msgbox([opn]),
            now=(BASE + timedelta(seconds=30)).timestamp(),
        )
        self.assertIn("turn turret", L.get_pending_dialog(s) or "")
        self.assertAlmostEqual(L.ages(s)["dialog"], 30, delta=1)

    def test_parse_msgbox_log_reads_dialog_without_lcs_log(self):
        opn = f"{ts(0)} 0001 Info DbTracer 'MessageBox : Dialog only'"
        s = L.parse_msgbox_log(
            msgbox_path=self._write_msgbox([opn]),
            now=(BASE + timedelta(seconds=5)).timestamp(),
        )
        self.assertIn("Dialog only", L.get_pending_dialog(s) or "")
        self.assertIsNone(s.xy)


class TestTimestampDstFold(unittest.TestCase):
    """DST fall-back safety: a naive local wall-clock repeats for an hour, so
    _parse_ts must pick the fold interpretation closest to now instead of
    letting a fixed-fold epoch trip every sub-2s *_log_max_age_s gate."""

    def test_fold_disambiguation_prefers_epoch_closest_to_now(self):
        # Ambiguous hour: candidates one hour apart; log lines are recent.
        self.assertEqual(L._fold_disambiguate(1000.0, 4600.0, 4595.0), 4600.0)
        self.assertEqual(L._fold_disambiguate(1000.0, 4600.0, 1005.0), 1000.0)

    def test_fold_disambiguation_unambiguous_time_is_identity(self):
        self.assertEqual(L._fold_disambiguate(500.0, 500.0, 0.0), 500.0)

    def test_fold_disambiguation_tie_prefers_first_fold(self):
        self.assertEqual(L._fold_disambiguate(0.0, 3600.0, 1800.0), 0.0)

    def test_parse_ts_unambiguous_matches_naive_timestamp(self):
        line = ts(0) + " GetStageHwPosition ..."
        self.assertEqual(L._parse_ts(line), BASE.timestamp())

    def test_parse_ts_rejects_garbage(self):
        self.assertIsNone(L._parse_ts("no timestamp here"))
        self.assertIsNone(L._parse_ts("2026-13-99 25:00:00.000000 bad"))


if __name__ == "__main__":
    unittest.main()
