"""C1 PaddleOCR-VL-1.6 on vLLM (OpenAI chat), whole page, with the card's OCR prompt.

The ``paddleocr_vl_1_6`` key speaks the AKC external-runner protocol, which no server
implements; this key reaches the same weights through a vLLM chat endpoint instead.
"""

from .openai_chat import ChatProfile, runner

PROVIDER = "paddleocr_vl_1_6_vllm"
MODEL = "PaddlePaddle/PaddleOCR-VL-1.6"
PROFILE = ChatProfile(
    provider=PROVIDER,
    model=MODEL,
    prompt="OCR:",
    prompt_source=(
        "card at c5630aba, transformers example: PROMPTS = {'ocr': 'OCR:', ...}, content "
        "[image, text]; the vLLM recipe (docs.vllm.ai, PaddleOCR-VL Usage Guide) sends the "
        "same prompt as [image_url, text] with temperature=0.0. The card's page-level parser "
        "is a two-stage pipeline (PP-DocLayoutV2 layout, then element prompts) and the card "
        "says its example is element-level only; this runner sends the whole page once. "
        "max_tokens: generic (the card's max_new_tokens=512 is for one element)."
    ),
    generation={"temperature": 0.0, "max_tokens": 8192},
)
run, config = runner(PROFILE)
