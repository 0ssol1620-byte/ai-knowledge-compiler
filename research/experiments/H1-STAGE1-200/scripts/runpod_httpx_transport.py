#!/usr/bin/env python3
"""A drop-in RunPod transport that needs no child process.

`RunPodCurlTransport` shells out to curl for every call. On a host whose commit
charge is exhausted, `CreateProcess` starts failing and every RunPod call fails
with it -- including the delete and the absence check that exist to stop a paid
Pod from being abandoned. That is not hypothetical: it leaked probe Pod
`b3rk1h2v9ciis2` (WinError 8) and later killed a v11 campaign inside
`verify_deleted` (WinError 1455).

This class speaks the same protocol over httpx, in-process. It is a behavioural
substitute, not a rewrite of policy: same URL allowlist, same pod-id validation,
same accepted status codes, and -- importantly -- the same error strings, because
`create_once_or_reconcile` decides whether a create was *ambiguous* by looking
for "transport failure" in the message. A network error that may or may not have
created a Pod must keep saying "transport failure" so that path still reconciles
by unique name instead of blindly retrying.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

PODS_URL = "https://rest.runpod.io/v1/pods"
GRAPHQL_URL = "https://api.runpod.io/graphql"
POD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")


class RunPodHttpxTransport:
    def __init__(self, *, api_key: str) -> None:
        if not api_key or any(ch.isspace() for ch in api_key):
            raise RuntimeError("RunPod API key is malformed")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "tavonel-runpod-httpx-transport/1.0",
        }

    @staticmethod
    def _detail(payload: Any) -> str:
        """A short quote of the server's own words.

        The curl transport threw away non-2xx bodies, so a RunPod 500 arrived as
        a bare status code and every diagnosis after it was guesswork. Only the
        response body is quoted -- the API key lives in the request headers and
        never appears here.
        """
        if payload is None:
            return ""
        text = payload if isinstance(payload, str) else repr(payload)
        text = " ".join(text.split())
        return f": {text[:400]}" if text else ""

    def _request(
        self,
        *,
        method: str,
        url: str,
        body: dict[str, Any] | None = None,
        timeout: int = 20,
    ) -> tuple[int, Any]:
        if not (url in (PODS_URL, GRAPHQL_URL) or url.startswith(PODS_URL + "/")):
            raise RuntimeError("RunPod httpx transport URL escaped allowlist")
        try:
            response = httpx.request(
                method,
                url,
                headers=self._headers,
                json=body,
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            # Indistinguishable from the curl transport's non-zero exit: the
            # request may or may not have reached RunPod. The wording is load
            # bearing -- create_once_or_reconcile keys on it.
            raise RuntimeError(f"RunPod httpx {method} transport failure") from exc
        if not response.content.strip():
            return response.status_code, None
        try:
            return response.status_code, response.json()
        except ValueError:
            if response.status_code >= 400:
                # A non-JSON error page is still the server explaining itself.
                return response.status_code, response.text
            raise RuntimeError("RunPod httpx transport returned malformed JSON") from None

    def list_pods(self) -> list[dict[str, Any]]:
        status, payload = self._request(method="GET", url=PODS_URL)
        if status != 200 or not isinstance(payload, list):
            raise RuntimeError(
                f"RunPod Pod list failed with status {status}{self._detail(payload)}"
            )
        return [dict(item) for item in payload if isinstance(item, dict)]

    def get_pod(self, pod_id: str) -> dict[str, Any]:
        if not POD_ID_RE.fullmatch(pod_id):
            raise RuntimeError("RunPod Pod id is malformed")
        status, payload = self._request(method="GET", url=f"{PODS_URL}/{pod_id}")
        if status != 200 or not isinstance(payload, dict):
            raise RuntimeError(f"RunPod Pod get failed with status {status}")
        return dict(payload)

    def create_pod(self, payload: dict[str, Any]) -> dict[str, Any]:
        status, body = self._request(method="POST", url=PODS_URL, body=payload, timeout=35)
        if status not in {200, 201} or not isinstance(body, dict):
            raise RuntimeError(
                f"RunPod Pod create failed with status {status}{self._detail(body)}"
            )
        return dict(body)

    def delete_pod(self, pod_id: str) -> None:
        if not POD_ID_RE.fullmatch(pod_id):
            raise RuntimeError("RunPod Pod id is malformed")
        status, _ = self._request(method="DELETE", url=f"{PODS_URL}/{pod_id}", timeout=30)
        if status not in {200, 202, 204, 404}:
            raise RuntimeError(f"RunPod Pod delete failed with status {status}")

    def graphql(self, *, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        status, payload = self._request(
            method="POST",
            url=GRAPHQL_URL,
            body={"query": query, "variables": variables or {}},
            timeout=20,
        )
        if status != 200 or not isinstance(payload, dict):
            raise RuntimeError(f"RunPod GraphQL failed with status {status}")
        if payload.get("errors"):
            raise RuntimeError("RunPod GraphQL returned errors")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("RunPod GraphQL returned invalid data")
        return dict(data)

    def reconcile_unique_pod(self, name: str) -> dict[str, Any] | None:
        matches = [item for item in self.list_pods() if str(item.get("name", "")) == name]
        if len(matches) > 1:
            raise RuntimeError("RunPod unique Pod name matched multiple records")
        return matches[0] if matches else None

    def verify_deleted(self, pod_id: str) -> bool:
        return all(str(item.get("id", "")) != pod_id for item in self.list_pods())
