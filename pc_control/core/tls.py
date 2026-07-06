"""
TLS для HTTPS-API.

Генерує самопідписаний сертифікат при першому запуску і зберігає cert.pem+key.pem
поруч із .env. Публічний CA (Let's Encrypt) не потрібен: мобільний клієнт довіряє
СВОЄМУ серверу через "pinning" — звіряє SHA-256 fingerprint сертифіката, отриманий
під час парування (у QR-коді). Це навіть надійніше за публічний CA, бо MITM не може
підсунути інший сертифікат, навіть якщо десь скомпрометують центр сертифікації.

Сертифікат довгоживучий (10 років) і прив'язаний до IP/хоста, які знаємо на старті.
Якщо файли вже існують — використовуємо їх (fingerprint стабільний між запусками,
інакше довелося б перепаровувати всі телефони).

Публічний інтерфейс:
    ensure_cert()      -> (cert_path, key_path)  — згенерувати за потреби, повернути шляхи
    fingerprint()      -> "AA:BB:..."            — SHA-256 відбиток (для QR/дашборду)
    ssl_context()      -> ssl.SSLContext         — готовий контекст для сервера
"""

from __future__ import annotations

import datetime
import ipaddress
import ssl
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from . import paths
from .logging_setup import get_logger

logger = get_logger("tls")

_CERT_VALIDITY_DAYS = 3650  # 10 років — щоб не перепаровувати телефони


def _san_list(hosts: list[str]) -> list[x509.GeneralName]:
    """Будує Subject Alternative Names: IP-адреси як IPAddress, решта — як DNSName."""
    names: list[x509.GeneralName] = []
    for h in hosts:
        h = h.strip()
        if not h:
            continue
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            names.append(x509.DNSName(h))
    return names


def _generate(cert_path: Path, key_path: Path, hosts: list[str]) -> None:
    """Створює новий self-signed сертифікат і приватний ключ."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "PC Control"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PC Control Home Server"),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)
    san = _san_list(hosts) or [x509.DNSName("localhost")]

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=_CERT_VALIDITY_DAYS))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    logger.info("Згенеровано новий TLS-сертифікат для хостів: %s", hosts)


def ensure_cert(hosts: list[str] | None = None) -> tuple[Path, Path]:
    """
    Гарантує наявність cert.pem/key.pem. Генерує лише якщо файлів немає
    (щоб fingerprint був стабільним і телефони не довелося перепаровувати).
    """
    cert_path, key_path = paths.TLS_CERT, paths.TLS_KEY
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path

    # хости: локальний, білий IP, localhost — щоб серт підходив звідусіль
    from .config import CONFIG
    default_hosts = ["127.0.0.1", "localhost"]
    public = getattr(CONFIG.api, "public_host", "").strip()
    if public:
        default_hosts.append(public)
    _generate(cert_path, key_path, hosts or default_hosts)
    return cert_path, key_path


def fingerprint() -> str:
    """SHA-256 відбиток сертифіката у вигляді AA:BB:CC:... (для QR та дашборду)."""
    ensure_cert()
    data = paths.TLS_CERT.read_bytes()
    cert = x509.load_pem_x509_certificate(data)
    fp = cert.fingerprint(hashes.SHA256())
    return ":".join(f"{b:02X}" for b in fp)


def ssl_context() -> ssl.SSLContext:
    """Готовий SSLContext для сервера (waitress/Flask)."""
    cert_path, key_path = ensure_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    return ctx
