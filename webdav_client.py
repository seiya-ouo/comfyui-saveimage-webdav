# -*- coding: utf-8 -*-
"""最小的 WebDAV 客户端（只用标准库，可脱离 ComfyUI 单独测试）。

特性：连接复用、MKCOL 目录缓存、失败重试、Basic 认证。
"""

from __future__ import annotations

import base64
import http.client
import ssl
import time
import urllib.parse


class WebDAVError(Exception):
    pass


class WebDAV:
    def __init__(self, base_url: str, username: str, password: str, timeout: int = 60):
        parsed = urllib.parse.urlsplit(base_url.rstrip("/"))
        self.scheme = parsed.scheme or "https"
        self.host = parsed.hostname
        self.port = parsed.port or (443 if self.scheme == "https" else 80)
        self.base_path = parsed.path.rstrip("/")
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        self.auth = f"Basic {token}"
        self.timeout = timeout
        self._conn = None
        self._dirs: set[str] = set()

    @staticmethod
    def _quote(path: str) -> str:
        return "/".join(urllib.parse.quote(p, safe="") for p in path.split("/") if p)

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _ensure_conn(self):
        if self._conn is None:
            if self.scheme == "https":
                self._conn = http.client.HTTPSConnection(
                    self.host, self.port, timeout=self.timeout,
                    context=ssl.create_default_context())
            else:
                self._conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)

    def _request(self, method: str, path: str, data: bytes | None = None,
                 headers: dict | None = None, ok=(200, 201, 204, 207)) -> int:
        hdrs = {"Authorization": self.auth, "User-Agent": "comfy-save-webdav/1.0"}
        if headers:
            hdrs.update(headers)
        req_path = self.base_path + "/" + self._quote(path)
        last = None
        for attempt in (1, 2):
            try:
                self._ensure_conn()
                self._conn.request(method, req_path, body=data, headers=hdrs)
                resp = self._conn.getresponse()
                body = resp.read()
                status = resp.status
                if resp.will_close:
                    self.close()
                if status not in ok:
                    raise WebDAVError(f"{method} {path} -> HTTP {status} {body[:200]!r}")
                return status
            except WebDAVError:
                raise
            except (http.client.HTTPException, OSError) as e:
                self.close()
                last = e
                if attempt == 1:
                    time.sleep(1.0)
                    continue
        raise WebDAVError(f"{method} {path} 网络错误: {last}")

    def ping(self) -> int:
        return self._request("PROPFIND", "/", headers={"Depth": "0"})

    def ensure_dir(self, path: str):
        cur = ""
        for seg in [s for s in path.split("/") if s]:
            cur = f"{cur}/{seg}" if cur else seg
            if cur in self._dirs:
                continue
            try:
                self._request("MKCOL", cur, ok=(200, 201, 204, 301, 405))
            except WebDAVError as e:
                if "405" not in str(e) and "301" not in str(e):
                    raise
            self._dirs.add(cur)

    def put_file(self, path: str, local_path: str, content_type: str = "application/octet-stream") -> int:
        with open(local_path, "rb") as fh:
            data = fh.read()
        return self._request("PUT", path, data=data,
                             headers={"Content-Type": content_type}, ok=(200, 201, 204))

    def delete(self, path: str) -> int:
        return self._request("DELETE", path, ok=(200, 204, 404))
