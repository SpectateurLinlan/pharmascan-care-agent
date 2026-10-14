"""Injected bounded HTTP transport. No globals, redirects, secrets or POST retries."""

from __future__ import annotations

import io
import json
import warnings
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx
from app.contracts.vision import VisionRequestError, VisionSchemaError, VisionUnavailable
from app.infrastructure.stage2_schema import JSONObject, Stage2Contract
from PIL import Image, UnidentifiedImageError


class HttpTransport:
    """Public injected seam for scripted test transports and production HTTP."""

    def __init__(self, *, base_url: str, timeout_seconds: float) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_json(self, path: str) -> JSONObject:
        raise NotImplementedError("Inject a concrete transport at the composition root")

    def post_json(self, path: str, payload: JSONObject) -> JSONObject:
        raise NotImplementedError("Inject a concrete transport at the composition root")

    def post_multipart(self, path: str, files: dict[str, bytes], data: dict[str, str]) -> JSONObject:
        raise NotImplementedError("Inject a concrete transport at the composition root")


def sanitize_reference_image(content: bytes) -> bytes:
    """Engineering input-quality checks, not a clinical recognition threshold."""
    clean = sanitize_image(content)
    with Image.open(io.BytesIO(clean)) as image:
        if min(image.size) < 64 or all(low == high for low, high in image.getextrema()):
            raise VisionSchemaError("Use a clear nonblank pill photo at least 64 pixels on each side")
    return clean


def sanitize_image(content: bytes, *, max_bytes: int = 8_000_000, max_pixels: int = 16_000_000) -> bytes:
    """Decode signature/MIME, cap pixels, remove EXIF by re-encoding to PNG."""
    if not content or len(content) > max_bytes:
        raise VisionSchemaError("image size outside allowed limits")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in ("PNG", "JPEG") or image.width * image.height > max_pixels:
                    raise VisionSchemaError("only bounded PNG/JPEG images supported")
                image.load()
                clean = Image.new("RGB", image.size)
                clean.paste(image.convert("RGB"))
                output = io.BytesIO()
                clean.save(output, format="PNG")
                normalized = output.getvalue()
                if len(normalized) > max_bytes:
                    raise VisionSchemaError("normalized image exceeds size limit")
                return normalized
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise VisionSchemaError("invalid or unsafe image") from exc


class HttpxStage2Transport(HttpTransport):
    """Retry GET 5xx/network only with injected bounded backoff; never repeat POST."""

    def __init__(
        self,
        *,
        client: httpx.Client,
        contract: Stage2Contract,
        base_url: str,
        timeout_seconds: float = 12,
        max_response_bytes: int = 2_000_000,
        get_retries: int = 1,
        sleep: Callable[[float], None],
    ) -> None:
        super().__init__(base_url=base_url, timeout_seconds=timeout_seconds)
        url = urlsplit(base_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Stage2 requires an HTTPS origin with no embedded credentials")
        if get_retries not in (0, 1, 2) or max_response_bytes < 1:
            raise ValueError("invalid retry/response limits")
        self._client, self._contract, self._sleep = client, contract, sleep
        self._limit, self._retries = max_response_bytes, get_retries

    def _request(self, method: str, path: str, **kwargs: object) -> JSONObject:
        # Fixed internal paths, not user- or LLM-supplied absolute URLs.
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("relative Stage2 path required")
        attempts = 1 + (self._retries if method == "GET" else 0)
        for attempt in range(attempts):
            try:
                with self._client.stream(
                    method,
                    self.base_url + path,
                    timeout=self.timeout_seconds,
                    follow_redirects=False,
                    headers={"Accept": "application/json"},
                    **kwargs,
                ) as response:
                    if response.status_code >= 500:
                        raise VisionUnavailable(f"Stage2 HTTP {response.status_code}")
                    if 300 <= response.status_code < 400:
                        raise VisionSchemaError("Stage2 redirect refused")
                    if "application/json" not in response.headers.get("content-type", "").lower():
                        raise VisionSchemaError("Stage2 returned non-JSON content")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > self._limit:
                            raise VisionSchemaError("Stage2 response too large")
                    try:
                        payload = json.loads(body)
                    except (ValueError, UnicodeDecodeError) as exc:
                        raise VisionSchemaError("Stage2 returned malformed JSON") from exc
                    if response.status_code >= 400:
                        error = self._contract.validate("Error", payload)
                        raise VisionRequestError(response.status_code, str(error["code"]))
                    if not isinstance(payload, dict):
                        raise VisionSchemaError("Stage2 response must be an object")
                    return payload
            except (httpx.TimeoutException, httpx.NetworkError, VisionUnavailable) as exc:
                if attempt + 1 == attempts:
                    raise VisionUnavailable("Stage2 unavailable; no recognition result") from exc
                self._sleep(0.2 * (2**attempt))
        raise VisionUnavailable("Stage2 unavailable")

    def get_json(self, path: str) -> JSONObject:
        return self._request("GET", path)

    def post_json(self, path: str, payload: JSONObject) -> JSONObject:
        return self._request("POST", path, json=payload)

    def post_multipart(self, path: str, files: dict[str, bytes], data: dict[str, str]) -> JSONObject:
        # identify accepts an UploadFile list named images; this single-photo
        # public Port sends one list part. Other supported endpoints use image.
        if path == "/v1/identify":
            field = "images"
        elif path in ("/v1/embed", "/v1/detect", "/v1/scan", "/v1/read-label"):
            field = "image"
        else:
            raise VisionSchemaError("unsupported Stage2 image upload endpoint")
        if set(files) != {field}:
            raise VisionSchemaError(f"v0.8.0 {path} multipart field must be {field}")
        content = sanitize_image(files[field])
        return self._request("POST", path, files={field: ("crop.png", content, "image/png")}, data=data)
