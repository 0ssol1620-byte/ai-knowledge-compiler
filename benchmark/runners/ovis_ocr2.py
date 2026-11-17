from typing import Any

from .openai_chat import run_chat

PROVIDER = "ovis_ocr2"
MODEL = "ATH-MaaS/OvisOCR2"


def run(
    case: dict[str, Any], *, endpoint: str | None, revision: str, allow_network: bool = False
) -> dict[str, Any]:
    return run_chat(
        PROVIDER, MODEL, case, endpoint=endpoint, revision=revision, allow_network=allow_network
    )
