"""C8 Xiaomi-OCR-0 on vLLM (smoke only), with the card's document prompt."""

from .openai_chat import ChatProfile, runner

PROVIDER = "xiaomi_ocr_0"
MODEL = "xiaomi-research/Xiaomi-OCR-0"
DOCUMENT_PROMPT = (
    "Extract all information from the main body of the document image and represent it "
    "in markdown format, ignoring headers and footers. Tables should be expressed in OTSL "
    "format, formulas in the document should be represented using LATEX format, and the "
    "parsing should be organized according to the reading order."
)
PROFILE = ChatProfile(
    provider=PROVIDER,
    model=MODEL,
    prompt=DOCUMENT_PROMPT,
    prompt_source=(
        "card at bbd8cf8d, Task prompts table, row 'Document' (the same PROMPT as its "
        "Transformers example); example decoding: max_new_tokens=4096, do_sample=False. "
        "Tables come back as OTSL, not HTML; the card's example serves through Transformers, "
        "vLLM serving is UNVERIFIED until the smoke."
    ),
    generation={"temperature": 0.0, "max_tokens": 4096},
)
run, config = runner(PROFILE)
