"""
HTTP-клієнт до ПК з TLS-pinning.

ВАЖЛИВО (Android): httpx і ssl імпортуються ЛІНИВО — лише коли реально робиться
запит. Причина: на Android-бандлі Flet `import ssl`/`import httpx` на рівні модуля
вішав старт (модуль _ssl підвантажувався проблемно) → додаток застрягав на
«Working…». Тепер старт UI не залежить від ssl; якщо з мережею проблема — вона
проявиться при запиті з видимою помилкою, а не мовчазним зависанням.

TLS-pinning: не довіряємо жодному CA, а звіряємо SHA-256 fingerprint сертифіката
ПК з тим, що отримали при паруванні (у QR). MITM неможливий.
"""

from __future__ import annotations

import hashlib


class ApiError(Exception):
    """Загальна помилка запиту (мережа/HTTP-статус)."""


class PinMismatch(ApiError):
    """Fingerprint сертифіката ПК не збігся з пінненим — можливий MITM."""


def _fingerprint_from_der(der: bytes) -> str:
    return ":".join(f"{b:02X}" for b in hashlib.sha256(der).digest())


def _make_pinned_transport(expected_fp: str, retries: int):
    """Створює httpx-transport, що звіряє fingerprint. Лінивий (httpx усередині)."""
    import ssl
    import httpx

    def _ssl_ctx():
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    expected = (expected_fp or "").upper().replace(" ", "")

    class PinnedTransport(httpx.HTTPTransport):
        def handle_request(self, request):
            response = super().handle_request(request)
            stream = response.extensions.get("network_stream")
            if stream is not None and expected:
                ssl_obj = stream.get_extra_info("ssl_object")
                if ssl_obj is not None:
                    der = ssl_obj.getpeercert(True)
                    actual = _fingerprint_from_der(der)
                    if actual != expected:
                        raise PinMismatch(
                            f"Fingerprint не збігся:\nочік. {expected[:20]}…\n"
                            f"факт. {actual[:20]}…"
                        )
            return response

    return PinnedTransport(verify=_ssl_ctx(), retries=retries)


class ApiClient:
    """Клієнт для одного ПК."""

    def __init__(self, pc: dict, timeout: float = 12.0, retries: int = 1):
        self.pc = pc
        self.timeout = timeout
        self.retries = retries
        # Persistent keep-alive клієнт для «гарячих» серій запитів (тачпад).
        # Створюється на вимогу (open_session), тримає TLS-зʼєднання відкритим,
        # тож рухи миші летять без нового рукостискання щоразу. Закривається
        # у close_session (вихід із меню / таймаут неактивності).
        self._session = None

    @property
    def base_url(self) -> str:
        scheme = "https" if self.pc.get("tls", True) else "http"
        host = self.pc["host"]
        port = self.pc.get("port", 5050)
        # стандартні порти не додаємо в URL (443/80) — чистий хост для Cloudflare
        if (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
            return f"{scheme}://{host}"
        return f"{scheme}://{host}:{port}"

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"Authorization": f"Bearer {self.pc['token']}"}
        if extra:
            h.update(extra)
        return h

    def _client(self, timeout: float | None = None):
        import httpx
        to = timeout if timeout is not None else self.timeout
        if self.pc.get("tls", True):
            fp = (self.pc.get("fingerprint", "") or "").strip()
            if fp:
                # self-signed сервер (прямий доступ) → pinning по fingerprint
                transport = _make_pinned_transport(fp, self.retries)
                return httpx.Client(transport=transport, timeout=to)
            # порожній fingerprint → Cloudflare: довірений CA. retries задаємо через
            # транспорт (httpx.Client НЕ приймає retries напряму — це давало
            # "Client.__init__() got an unexpected keyword argument 'retries'").
            transport = httpx.HTTPTransport(retries=self.retries)
            return httpx.Client(timeout=to, transport=transport, verify=True)
        transport = httpx.HTTPTransport(retries=self.retries)
        return httpx.Client(timeout=to, transport=transport)

    def open_session(self) -> None:
        """Відкриває persistent keep-alive зʼєднання (для тачпада тощо).
        Наступні request() підуть по ньому без нового TLS-рукостискання.
        Безпечно викликати повторно — якщо сесія вже є, нічого не робить."""
        if self._session is None:
            self._session = self._client()

    def close_session(self) -> None:
        """Закриває persistent зʼєднання. Безпечно навіть якщо його нема."""
        s, self._session = self._session, None
        if s is not None:
            try:
                s.close()
            except Exception:
                pass

    def request(self, method: str, path: str, *, params: dict | None = None):
        import httpx
        url = self.base_url + path
        try:
            if self._session is not None:
                # persistent-сесія: НЕ закриваємо після запиту (keep-alive)
                resp = self._session.request(method.upper(), url, params=params,
                                             headers=self._headers())
            else:
                with self._client() as client:
                    resp = client.request(method.upper(), url, params=params,
                                          headers=self._headers())
        except PinMismatch:
            raise
        except httpx.HTTPError as e:
            # Persistent-сокет міг померти (сервер закрив keep-alive) — скидаємо
            # сесію, щоб наступний виклик підняв свіже зʼєднання.
            self.close_session()
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

    # -------------------------------------------------- POST / файли
    def _body_request(self, path: str, *, params=None, json=None,
                      content=None, files=None, data=None, content_type=None):
        """POST із тілом (json / сирі байти / multipart). Не через persistent-сесію
        (файли можуть бути великі — окремий клієнт із запасом по таймауту)."""
        import httpx
        url = self.base_url + path
        headers = self._headers()
        if content_type and content is not None:
            headers["Content-Type"] = content_type
        try:
            with self._client(timeout=120.0) as client:
                resp = client.post(url, params=params, json=json,
                                   content=content, files=files, data=data,
                                   headers=headers)
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

    def post_json(self, path: str, json: dict | None = None,
                  params: dict | None = None) -> dict:
        r = self._body_request(path, params=params, json=json or {})
        try:
            return r.json()
        except Exception:
            return {"text": r.text}

    def post_multipart(self, path: str, files: dict, data: dict | None = None) -> str:
        """files={"file": (name, bytes, mime)} — відправка файлу на ПК."""
        return self._body_request(path, files=files, data=data).text

    def post_bytes(self, path: str, content: bytes, *, content_type: str,
                   params: dict | None = None) -> str:
        return self._body_request(path, content=content,
                                  content_type=content_type, params=params).text

    def download_to(self, path: str, dest_path: str, params: dict | None = None,
                    on_progress=None) -> str:
        """Стрімить файл із ПК у dest_path (не тримає в RAM). Повертає dest_path."""
        import httpx
        url = self.base_url + path
        try:
            with self._client(timeout=300.0) as client:
                with client.stream("GET", url, params=params,
                                   headers=self._headers()) as resp:
                    if resp.status_code >= 400:
                        raise ApiError(f"Помилка {resp.status_code}")
                    total = int(resp.headers.get("Content-Length", 0) or 0)
                    done = 0
                    with open(dest_path, "wb") as f:
                        for chunk in resp.iter_bytes(65536):
                            f.write(chunk)
                            done += len(chunk)
                            if on_progress and total:
                                try:
                                    on_progress(done, total)
                                except Exception:
                                    pass
        except PinMismatch:
            raise
        except httpx.HTTPError as e:
            raise ApiError(f"Мережева помилка: {e}") from e
        return dest_path

    def manifest(self) -> dict:
        return self.get_json("/manifest")

    def ping(self) -> bool:
        try:
            self.request("GET", "/devices")
            return True
        except ApiError:
            return False


def pair(host: str, port: int, tls: bool, pin: str, name: str,
         expected_fp: str, timeout: float = 12.0) -> dict:
    """POST /pair. Лінивий httpx. Повертає {token, fingerprint, server_name}."""
    import httpx
    scheme = "https" if tls else "http"
    # чистий URL без стандартного порту (443/80) — для Cloudflare
    if (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
        url = f"{scheme}://{host}/pair"
    else:
        url = f"{scheme}://{host}:{port}/pair"
    if tls and (expected_fp or "").strip():
        # self-signed сервер → pinning
        transport = _make_pinned_transport(expected_fp, 1)
        client = httpx.Client(transport=transport, timeout=timeout)
    elif tls:
        # Cloudflare (порожній fingerprint) → довірений CA
        client = httpx.Client(timeout=timeout, verify=True)
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
