"""C6 TeleOCR on vLLM only; nothing from its unlicensed code repository is used."""

from .openai_chat import ChatProfile, runner
from .vlm import GENERIC_PROMPT

PROVIDER = "teleocr"
MODEL = "XingChen-AGI/TeleOCR"
PROFILE = ChatProfile(
    provider=PROVIDER,
    model=MODEL,
    prompt=GENERIC_PROMPT,
    prompt_source="generic: the card at a32e21d4 publishes no prompt or generation settings",
    generation={"temperature": 0.0, "max_tokens": 8192},
)
run, config = runner(PROFILE)
