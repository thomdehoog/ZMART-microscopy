"""
Self-signed certificates for the fake gateway.
==============================================
The real ZEN API Gateway only talks TLS and generates its own self-signed
root certificate on first start. The fake gateway does the same so the
driver's TLS code path (``build_ssl_context``) is exercised for real: a
certificate for ``localhost`` / ``127.0.0.1`` is written next to the key, and
the ``.pem`` is what ``config.ini`` points at as ``cert_file``.

Two ways to make the certificate, tried in this order:

1. the ``cryptography`` Python package, when it is installed;
2. the ``openssl`` command-line tool, when it is on the PATH.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import shutil
import subprocess
from importlib.util import find_spec
from pathlib import Path

CERT_NAME = "FakeZenApiGatewayRootCA.pem"
KEY_NAME = "FakeZenApiGatewayRootCA.key"


def ensure_certificate(work_dir: str | Path, *, hostname: str = "localhost") -> tuple[Path, Path]:
    """Return ``(cert_pem, key_pem)`` under ``work_dir``, creating them when missing.

    The certificate is valid for ``hostname``, ``localhost`` and ``127.0.0.1``
    (the fake gateway is meant to run on the same computer). Raises
    ``RuntimeError`` when neither ``cryptography`` nor ``openssl`` is
    available to create one.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    cert, key = work_dir / CERT_NAME, work_dir / KEY_NAME
    if cert.exists() and key.exists():
        return cert, key
    names = sorted({hostname, "localhost"})
    if find_spec("cryptography") is not None:
        _with_cryptography(cert, key, names)
    elif shutil.which("openssl"):
        _with_openssl(cert, key, names)
    else:
        raise RuntimeError(
            "cannot create a certificate for the fake gateway: install the "
            "'cryptography' package (pip install cryptography) or the openssl "
            "command-line tool"
        )
    return cert, key


def _with_cryptography(cert: Path, key: Path, names: list[str]) -> None:
    import datetime
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Fake ZEN API Gateway")])
    now = datetime.datetime.now(datetime.timezone.utc)
    san = [x509.DNSName(n) for n in names] + [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(private_key, hashes.SHA256())
    )
    key.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))


def _with_openssl(cert: Path, key: Path, names: list[str]) -> None:
    san = ",".join([f"DNS:{n}" for n in names] + ["IP:127.0.0.1"])
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "3650",
            "-subj",
            "/CN=Fake ZEN API Gateway",
            "-addext",
            f"subjectAltName={san}",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
        ],
        check=True,
        capture_output=True,
    )
