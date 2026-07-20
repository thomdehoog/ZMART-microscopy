"""Command timing constants — data only, imported by every layer.

NOTE: runtime consumers (``commands.dispatch``, ``commands.confirmations``,
``commands.confirm_select_job``, ``readers.api_reader``) read these at call
time (``timing.CONFIRM_POLL_S``), so reassigning them at runtime (e.g. a
test monkeypatch) takes effect. Exception: ``config.profiles`` captures
them into dataclass field defaults at import, so profile fields keep the
values from process start. To tune for your hardware, edit these constants.
"""

RECEIPT_TIMEOUT = 2  # UpdateAwaitReceipt transport ACK deadline (a true timeout:
# expiry after transport retries is a hard delivery failure)
CONFIRM_POLL_S = 3  # Per-attempt readback poll window (NOT a timeout): poll the
# readback for this long, then re-fire and poll again up to max_confirm_attempts;
# exhaustion returns unconfirmed, never a hard fail.
