"""Dry-run generator for a temporary RunPod image-builder pod.

Nothing in this module executes anything: it produces a pod spec (name,
image, disk, GPU-free) and the exact remote build script
(``build_on_pod.sh``) a person or a later, explicitly-executed lane would run
over SSH on that pod. No pod is created, no image is pulled, no registry
token ever appears in the spec -- the registry credential is delivered over
SSH at build time (see BUILD_PLAN.md's rationale: pod *env* is readable
through the RunPod provider API, so a registry push credential never goes in
``env``).

Follows the ``infra/runpod/v6/builder_pod.py`` pattern (temporary builder,
cost-bounded, GPU-free is even safer than that module's GPU builder because
this one never needs a GPU at all -- buildah/podman build CUDA-*runtime*
images the same way they build any other OCI image; the GPU is only needed
to *run* the resulting container, not to *build* it).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Final, cast

_MODEL_KEY_RE: Final = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
_POD_NAME_RE: Final = re.compile(r"^arena-builder-[a-z0-9-]{3,50}$")


class BuilderPodPlanError(ValueError):
    """Raised for a malformed *input* to a generator, never for a network outcome."""


@dataclass(frozen=True, slots=True)
class BuilderPodPlan:
    """A dry-run builder-pod spec. Nothing here has been sent to RunPod."""

    model_key: str
    pod_name: str
    disk_gb: int
    volume_gb: int
    ssh_public_key: str

    def __post_init__(self) -> None:
        if not _MODEL_KEY_RE.fullmatch(self.model_key):
            raise BuilderPodPlanError(f"invalid model_key: {self.model_key!r}")
        if not _POD_NAME_RE.fullmatch(self.pod_name):
            raise BuilderPodPlanError(f"invalid pod_name: {self.pod_name!r}")
        if not 40 <= self.disk_gb <= 400:
            raise BuilderPodPlanError("disk_gb must be between 40 and 400")
        if not 0 <= self.volume_gb <= 400:
            raise BuilderPodPlanError("volume_gb must be between 0 and 400")
        if not self.ssh_public_key.startswith(("ssh-ed25519 ", "ssh-rsa ")):
            raise BuilderPodPlanError("ssh_public_key must be an ssh-ed25519 or ssh-rsa key")

    def provider_request_dry_run(self) -> dict[str, object]:
        """The exact provider request this plan *would* send under --execute.

        Deliberately GPU-free: ``computeType`` is CPU and no ``gpuTypeIds`` is
        set, matching MP §15.1's "buildah bud needs no GPU to produce a
        CUDA-runtime image" (the GPU only matters at inference time).
        """
        return {
            "name": self.pod_name,
            # A minimal, widely-mirrored base with buildah preinstalled is
            # resolved at execution time, never a floating ":latest".
            "cloudType": "SECURE",
            "computeType": "CPU",
            "containerDiskInGb": self.disk_gb,
            "volumeInGb": self.volume_gb,
            "volumeMountPath": "/workspace",
            "ports": ["22/tcp"],
            "supportPublicIp": True,
            "interruptible": False,
            "dockerEntrypoint": ["/bin/bash", "-c"],
            "dockerStartCmd": [_bootstrap_script()],
            "env": {
                "PUBLIC_KEY": self.ssh_public_key,
                "ARENA_BUILDER_ROLE": "temporary-image-builder-not-a-benchmark-runtime",
            },
        }

    def redacted_request(self) -> dict[str, object]:
        """Same shape as ``provider_request_dry_run`` with the key redacted,
        safe to place in a receipt or a log line."""
        request = self.provider_request_dry_run()
        env = cast("dict[str, object]", request["env"])
        redacted_env = dict(env)
        redacted_env["PUBLIC_KEY"] = "redacted"
        request["env"] = redacted_env
        return request


def _bootstrap_script() -> str:
    # No model-specific content: this only installs buildah/podman and starts
    # sshd. The per-model build happens over SSH via build_on_pod.sh, after a
    # human or an explicitly-executed controller step delivers the registry
    # token -- the token is never baked into this bootstrap or into pod env.
    return (
        "set -euo pipefail\n"
        "export DEBIAN_FRONTEND=noninteractive\n"
        "apt-get update -qq\n"
        "apt-get install -y -qq --no-install-recommends "
        "openssh-server git buildah podman jq curl ca-certificates uidmap fuse-overlayfs\n"
        "rm -rf /var/lib/apt/lists/*\n"
        "install -d -m 0700 /root/.ssh\n"
        'printf \'%s\\n\' "$PUBLIC_KEY" > /root/.ssh/authorized_keys\n'
        "chmod 0600 /root/.ssh/authorized_keys\n"
        "install -d -m 0755 /run/sshd /workspace/arena-builder\n"
        "buildah --version\n"
        "exec /usr/sbin/sshd -D -e\n"
    )


def build_on_pod_script(
    *,
    model_key: str,
    dockerfile: str,
    context_dir: str,
    registry_target: str,
    image_tag: str,
) -> str:
    """Deterministic remote build script content for a single model_key.

    Delivered over SSH and run on the builder pod; never executed by this
    process. Pure string formatting only -- calling this twice with the same
    arguments produces byte-identical output (required for the determinism
    test in tests/build).
    """
    if not _MODEL_KEY_RE.fullmatch(model_key):
        raise BuilderPodPlanError(f"invalid model_key: {model_key!r}")
    for value, label in (
        (dockerfile, "dockerfile"),
        (context_dir, "context_dir"),
        (registry_target, "registry_target"),
        (image_tag, "image_tag"),
    ):
        if not value or any(character in value for character in ("\n", "\r", "\x00")):
            raise BuilderPodPlanError(f"invalid {label}: {value!r}")

    full_target = f"{registry_target}:{image_tag}"
    return (
        "#!/usr/bin/env bash\n"
        "# Generated by build/builder_pod_plan.py -- deterministic for a given\n"
        f"# (model_key={model_key}, dockerfile, context_dir, registry_target, image_tag).\n"
        "# The registry credential arrives as $ARENA_REGISTRY_TOKEN over this same SSH\n"
        "# session's environment (never pod env, never a file left on disk) and is used\n"
        "# once via 'buildah login --password-stdin', then unset.\n"
        "set -euo pipefail\n"
        f"MODEL_KEY={model_key!r}\n"
        f"DOCKERFILE={dockerfile!r}\n"
        f"CONTEXT_DIR={context_dir!r}\n"
        f"TARGET={full_target!r}\n"
        'if [ -z "${ARENA_REGISTRY_TOKEN:-}" ]; then\n'
        '  echo "ARENA_REGISTRY_TOKEN is not set;'
        ' refusing to build without a push credential" >&2\n'
        "  exit 1\n"
        "fi\n"
        'echo "$ARENA_REGISTRY_TOKEN" | buildah login --username tavonel-arena-builder '
        "--password-stdin ghcr.io\n"
        "unset ARENA_REGISTRY_TOKEN\n"
        'buildah bud --format oci --file "$DOCKERFILE" --tag "$TARGET" "$CONTEXT_DIR"\n'
        'buildah push "$TARGET" "docker://$TARGET"\n'
        "# Resolve the pushed digest independently rather than trusting push output.\n"
        'skopeo inspect --format "{{.Digest}}" "docker://$TARGET" '
        "> /workspace/arena-builder/pushed_digest.txt\n"
        'echo "build complete for $MODEL_KEY: '
        '$(cat /workspace/arena-builder/pushed_digest.txt)"\n'
    )


def render_plan(plan: BuilderPodPlan) -> str:
    """JSON rendering of the redacted request, for a receipt or a log line."""
    return json.dumps(plan.redacted_request(), indent=2, sort_keys=True, ensure_ascii=True)


__all__ = [
    "BuilderPodPlan",
    "BuilderPodPlanError",
    "build_on_pod_script",
    "render_plan",
]
