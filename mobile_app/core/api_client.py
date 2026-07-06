"""
HTTP-клієнт до ПК з TLS-pinning.

Проблема self-signed: публічний CA не підписував наш сертифікат, тож звичайна
перевірка ланцюга провалиться. Рішення — pinning: ми НЕ довіряємо жодному CA,
а звіряємо SHA-256 fingerprint сертифіката ПК з тим, що отримали під час
парування (у QR). Якщо збігається — з'єднання довірене; це унеможливлює MITM
(підмінити сертифікат не вийде, бо fingerprint не зійдеться).

Реалізація:
  * httpx з verify=ssl-контекстом, який НЕ перевіряє ланцюг/хост (self-signed),
  * після рукостискання дістаємо DER сертифіката й рахуємо його SHA-256,
  * якщо не збігається з пінненим — рвемо з'єднання (PinMismatch).

Кожен запит несе Authorization: Bearer <token>. Є короткий retry на мережеві збої.
"""

from __future__ import annotations

import hashlib
import ssl

import httpx


class ApiError(Exception):
    """Загальна помилка запиту (мережа/HTTP-статус)."""


class PinMismatch(ApiError):
    """Fingerprint сертифіката ПК не збігся з пінненим — можливий MITM."""


def _fingerprint_from_der(der: bytes) -> str:
    return ":".join(f"{b:02X}" for b in hashlib.sha256(der).digest())


class PinnedTransport(httpx.HTTPTransport):
    """Transport, що після з'єднання звіряє fingerprint сертифіката сервера."""

    def __init__(self, expected_fp: str, **kwargs):
        self._expected = (expected_fp or "").upper().replace(" ", "")
        super().__init__(**kwargs)

    def handle_request(self, request):
        response = super().handle_request(request)
        # network_stream доступний через extensions
        stream = response.extensions.get("network_stream")
        if stream is not None and self._expected:
            ssl_obj = stream.get_extra_info("ssl_object")
            if ssl_obj is not None:
                der = ssl_obj.getpeercert(True)  # binary_form=True (позиційно)
                actual = _fingerprint_from_der(der)
                if actual != self._expected:
                    raise PinMismatch(
                        f"Fingerprint не збігся:\nочік. {self._expected[:20]}…\n"
                        f"факт. {actual[:20]}…"
                    )
        return response


def _pinned_ssl_context() -> ssl.SSLContext:
    """SSL-контекст для self-signed: шифрування є, але ланцюг/хост не перевіряємо
    (довіру дає pinning fingerprint, не CA)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class ApiClient:
    """Клієнт для одного ПК."""

    def __init__(self, pc: dict, timeout: float = 12.0, retries: int = 1):
        self.pc = pc
        self.timeout = timeout
        self.retries = retries

    # ------------------------------------------------------------ службове
    @property
    def base_url(self) -> str:
        scheme = "https" if self.pc.get("tls", True) else "http"
        return f"{scheme}://{self.pc['host']}:{self.pc['port']}"

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"Authorization": f"Bearer {self.pc['token']}"}
        if extra:
            h.update(extra)
        return h

    def _client(self) -> httpx.Client:
        if self.pc.get("tls", True):
            transport = PinnedTransport(
                self.pc.get("fingerprint", ""),
                verify=_pinned_ssl_context(),
                retries=self.retries,
            )
            return httpx.Client(transport=transport, timeout=self.timeout)
        return httpx.Client(timeout=self.timeout, retries=self.retries)

    # ------------------------------------------------------------ запити
    def request(self, method: str, path: str, *, params: dict | None = None) -> httpx.Response:
        url = self.base_url + path
        try:
            with self._client() as client:
                resp = client.request(method.upper(), url, params=params,
                                       headers=self._headers())
        except PinMismatch:
            raise
        except httpx.HTTPError as e:
            raise ApiError(f"Мережева помилка: {e}") from e
        if resp.status_code == 403:
            raise ApiError("Доступ заборонено (токен недійсний або IP забанено).")
        if resp.status_code == 429:
            raise ApiError("Забагато запитів, спробуй за мить.")
        if resp.status_code >= 400:
            raise ApiError(f"Помилка сервера {resp.status_code}: {resp.text[:120]}")
        return resp

    def get_text(self, path: str, params: dict | None = None) -> str:
        return self.request("GET", path, params=params).text

    def get_json(self, path: str, params: dict | None = None) -> dict:
        return self.request("GET", path, params=params).json()

    def get_bytes(self, path: str, params: dict | None = None) -> bytes:
        return self.request("GET", path, params=params).content

    def manifest(self) -> dict:
        return self.get_json("/manifest")

    def ping(self) -> bool:
        """Швидка перевірка зв'язку (health + що токен валідний через /devices)."""
        try:
            self.request("GET", "/devices")
            return True
        except ApiError:
            return False


# ---------------------------------------------------------------- парування

def pair(host: str, port: int, tls: bool, pin: str, name: str,
         expected_fp: str, timeout: float = 12.0) -> dict:
    """
    Виконує POST /pair. Повертає {token, fingerprint, server_name}.
    Звіряє fingerprint сервера з тим, що у QR (pinning уже на етапі парування).
    """
    scheme = "https" if tls else "http"
    url = f"{scheme}://{host}:{port}/pair"
    if tls:
        transport = PinnedTransport(expected_fp, verify=_pinned_ssl_context(), retries=1)
        client = httpx.Client(transport=transport, timeout=timeout)
    else:
        client = httpx.Client(timeout=timeout)
    try:
        resp = client.post(url, json={"pin": pin, "name": name})
    except PinMismatch:
        raise
    except httpx.HTTPError as e:
        raise ApiError(f"Не вдалося з'єднатися з ПК: {e}") from e
    finally:
        client.close()

    if resp.status_code == 403:
        raise ApiError("Невірний PIN або IP тимчасово забанено.")
    if resp.status_code >= 400:
        raise ApiError(f"Помилка парування {resp.status_code}: {resp.text[:120]}")
    return resp.json()
