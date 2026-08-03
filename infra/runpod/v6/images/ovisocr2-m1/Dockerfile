# syntax=docker/dockerfile:1.7
FROM vllm/vllm-openai@sha256:e1668bce9790a4b86682f8fcc99678153a13e12dc70e05348d8e239ffa474b05

ARG MODEL_REVISION=65c619d374b55d4152e85150fc1b003700bc1f0c
ARG MODEL_SAFETENSORS_SHA256=9270560288656ece5cb3a6989001afcf5af8d223bceed4a423c33a008861d009

ENV DEBIAN_FRONTEND=noninteractive \
    FOLYNTA_MODEL_ROOT=/opt/folynta/models/OvisOCR2 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_ENABLE_HF_TRANSFER=0 \
    MODEL_REVISION=${MODEL_REVISION}

USER root
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends openssh-server ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd /root/.ssh /opt/folynta/models/OvisOCR2

RUN python3 - <<'PY'
from importlib.metadata import version

expected = {
    "vllm": "0.22.1",
    "huggingface-hub": "1.17.0",
    "pillow": "12.2.0",
    "transformers": "5.10.2",
}
actual = {name: version(name) for name in expected}
if actual != expected:
    raise SystemExit(f"image dependency mismatch: {actual!r}")
PY

RUN hf download ATH-MaaS/OvisOCR2 \
      --revision "${MODEL_REVISION}" \
      --local-dir "${FOLYNTA_MODEL_ROOT}" \
    && printf '%s  %s\n' \
      "${MODEL_SAFETENSORS_SHA256}" \
      "${FOLYNTA_MODEL_ROOT}/model.safetensors" \
      | sha256sum --check --strict \
    && find "${FOLYNTA_MODEL_ROOT}" -type f -exec chmod 0444 {} +

COPY benchmark/runpod_eval/bootstrap_ovisocr2_m1.sh /opt/folynta/verify-runtime.sh
COPY infra/runpod/v6/images/ovisocr2-m1/start-ssh.sh /opt/folynta/start-ssh.sh
RUN chmod 0555 /opt/folynta/verify-runtime.sh /opt/folynta/start-ssh.sh \
    && { \
      echo "base_image=vllm/vllm-openai@sha256:e1668bce9790a4b86682f8fcc99678153a13e12dc70e05348d8e239ffa474b05"; \
      echo "model_revision=${MODEL_REVISION}"; \
      echo "model_safetensors_sha256=${MODEL_SAFETENSORS_SHA256}"; \
      python3 --version; \
      python3 -m pip freeze | LC_ALL=C sort; \
    } > /opt/folynta/baked-runtime-receipt.txt \
    && chmod 0444 /opt/folynta/baked-runtime-receipt.txt

EXPOSE 22
ENTRYPOINT ["/opt/folynta/start-ssh.sh"]
