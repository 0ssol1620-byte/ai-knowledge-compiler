"""C7 OvisOCR3 on vLLM, document-markdown mode as its card prescribes."""

from .openai_chat import ChatProfile, runner

PROVIDER = "ovis_ocr3"
MODEL = "ATH-MaaS/OvisOCR3"
# prompts/document_markdown.txt at 5b252386 (512 B, sha256 dbf31d58...c32997c), fetched as
# public metadata; the card's "Document parsing" table points Markdown mode at this file.
DOCUMENT_MARKDOWN_PROMPT = (
    "Extract all readable content from the image in natural human reading order and "
    "output the result as a single Markdown document. For charts or images, represent "
    'them using an HTML image tag: <img src="images/bbox_{left}_{top}_{right}_{bottom}'
    '.jpg" />, where left, top, right, bottom are bounding box coordinates scaled to '
    "[0, 1000). Format formulas as LaTeX. Format tables as HTML: <table>...</table>. "
    "Transcribe all other text as standard Markdown. Preserve the original text "
    "without translation or paraphrasing."
)
PROFILE = ChatProfile(
    provider=PROVIDER,
    model=MODEL,
    prompt=DOCUMENT_MARKDOWN_PROMPT,
    prompt_source=(
        "card at 5b252386: Markdown mode = prompts/document_markdown.txt (sha256 "
        "dbf31d5899a86047ce0cd4d0d12cdc5616df1bea5d9a600b823098442c32997c); inference "
        "example: SamplingParams(max_tokens=16384, temperature=0.0), enable_thinking=False, "
        "min_pixels 448*448, max_pixels 2880*2880"
    ),
    generation={
        "temperature": 0.0,
        "max_tokens": 16_384,
        "mm_processor_kwargs": {
            "images_kwargs": {"min_pixels": 448 * 448, "max_pixels": 2_880 * 2_880}
        },
        "chat_template_kwargs": {"enable_thinking": False},
    },
)
run, config = runner(PROFILE)
