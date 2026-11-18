"""C2 OvisOCR2 on vLLM, with the vendor prompt and limits of the stage-2 runner."""

from .openai_chat import ChatProfile, runner

PROVIDER = "ovis_ocr2"
MODEL = "ATH-MaaS/OvisOCR2"
# Same text as VENDOR_PROMPT in benchmark/runpod_eval/ovisocr2_stage2.py (a test binds them);
# that module is a GPU-worker script and is not importable from the runner package.
VENDOR_PROMPT = (
    "Extract all readable content from the image in natural human reading order and "
    "output the result as a single Markdown document. For charts or images, represent "
    'them using an HTML image tag: <img src="images/bbox_{left}_{top}_{right}_{bottom}'
    '.jpg" />, where left, top, right, bottom are bounding box coordinates scaled to '
    "[0, 1000). Format formulas as LaTeX. Format tables as HTML: <table>...</table>. "
    "Transcribe all other text as standard Markdown.\nPreserve the original text "
    "without translation or paraphrasing."
)
PROFILE = ChatProfile(
    provider=PROVIDER,
    model=MODEL,
    prompt=VENDOR_PROMPT,
    prompt_source=(
        "card (vendor inference contract), reused from benchmark/runpod_eval/ovisocr2_stage2.py: "
        "VENDOR_PROMPT, max_tokens 16384, temperature 0, min_pixels 448*448, "
        "max_pixels 2880*2880, enable_thinking false"
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
