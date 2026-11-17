"""C4 MiniCPM-OCR-1.0 on vLLM, whole page, with the card's page-level recognition prompt."""

from .openai_chat import ChatProfile, runner

PROVIDER = "minicpm_ocr_1"
MODEL = "openbmb/MiniCPM-OCR-1.0"
PROFILE = ChatProfile(
    provider=PROVIDER,
    model=MODEL,
    prompt="Text Recognition:",
    prompt_source=(
        "card at 883ca368, Recognition guide: region 'Text block / Paragraph / Title / Page' "
        "-> prompt 'Text Recognition:'. The card's full parser is a two-stage SDK pipeline "
        "(PP-DocLayoutV3 layout, then region prompts); this runner sends the whole page "
        "once. Generation settings: generic (the card publishes none)."
    ),
    generation={"temperature": 0.0, "max_tokens": 8192},
)
run, config = runner(PROFILE)
