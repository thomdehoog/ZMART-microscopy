"""gRPC status-code classification."""

from mock_zen_api import FakeGRPCError

from zenapi.commands.errors import classify_grpc_error


def test_transient_codes():
    for code in ("UNAVAILABLE", "DEADLINE_EXCEEDED", "ABORTED", "RESOURCE_EXHAUSTED", "CANCELLED"):
        r = classify_grpc_error(FakeGRPCError(code, "x"))
        assert r["transient"] is True, code
        assert code in r["error"]


def test_permanent_codes():
    for code in ("INVALID_ARGUMENT", "NOT_FOUND", "FAILED_PRECONDITION", "UNAUTHENTICATED"):
        r = classify_grpc_error(FakeGRPCError(code, "x"))
        assert r["transient"] is False, code


def test_unknown_code_is_permanent():
    r = classify_grpc_error(FakeGRPCError("WEIRD_CODE", "?"))
    assert r["transient"] is False


def test_timeout_is_transient():
    r = classify_grpc_error(TimeoutError("deadline"))
    assert r["transient"] is True


def test_status_less_error_is_transient():
    r = classify_grpc_error(RuntimeError("socket dropped"))
    assert r["transient"] is True
