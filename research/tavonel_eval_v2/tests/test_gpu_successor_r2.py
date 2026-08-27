from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path
from typing import ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "research" / "tavonel_eval_v2" / "tools"
sys.path.insert(0, str(TOOLS))

import gpu_successor_r2 as r2  # noqa: E402


class Missing(Exception):
    response: ClassVar = {"Error": {"Code": "NoSuchKey"}}


class MockS3:
    def __init__(self):
        self.objects = {}
        self.puts = 0

    def head_object(self, *, Bucket, Key):
        del Bucket
        if Key not in self.objects:
            raise Missing
        return {"Metadata": self.objects[Key][1]}

    def put_object(self, *, Bucket, Key, Body, Metadata, **kwargs):
        del Bucket, kwargs
        self.puts += 1
        self.objects[Key] = (Body, Metadata)

    def get_object(self, *, Bucket, Key):
        del Bucket
        return {"Body": io.BytesIO(self.objects[Key][0])}


def test_r2_transport_puts_once_and_reuses_exact_content_address():
    client = MockS3()
    transport = r2.S3CompatibleObjectTransport(client=client, bucket="research", prefix="frozen")
    body = b'{"exact":true}'
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    key = f"gpu-successor/inputs/{digest[7:]}.json"
    transport.put_if_absent(key, body, digest)
    transport.put_if_absent(key, body, digest)
    assert client.puts == 1
    assert transport.get(key) == body


def test_r2_transport_refuses_existing_digest_drift():
    client = MockS3()
    transport = r2.S3CompatibleObjectTransport(client=client, bucket="research")
    client.objects["gpu/input.json"] = (b"other", {"tavonel-sha256": "sha256:" + "0" * 64})
    body = b"expected"
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    with pytest.raises(r2.R2TransportError, match="another digest"):
        transport.put_if_absent("gpu/input.json", body, digest)


def test_r2_transport_has_no_credential_discovery_surface():
    source = (TOOLS / "gpu_successor_r2.py").read_text(encoding="utf-8")
    assert "os.environ" not in source
    assert "boto3.client" not in source
