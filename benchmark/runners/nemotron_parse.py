"""C5 Nemotron-3.5-Parse on vLLM, single pass, with the card's task prompt and settings."""

from .openai_chat import ChatProfile, runner

PROVIDER = "nemotron_parse_3_5"
MODEL = "nvidia/Nemotron-3.5-Parse"
TASK_PROMPT = "</s><s><predict_bbox><predict_classes><output_markdown><predict_text_in_pic>"
PROFILE = ChatProfile(
    provider=PROVIDER,
    model=MODEL,
    prompt=TASK_PROMPT,
    prompt_source=(
        "card at ea2e1fe4, vLLM section: 'TASK_PROMPT = \"</s><s><predict_bbox><predict_classes>"
        "<output_markdown><predict_text_in_pic>\"'; content [text, image_url]; "
        '\'temperature=0, max_tokens=8744, extra_body={"top_k": 1, "repetition_penalty": 1.1, '
        '"skip_special_tokens": False}\'. The raw output keeps class and box tokens; the '
        "card's postprocessing helpers are not run here."
    ),
    generation={
        "temperature": 0,
        "max_tokens": 8744,
        "top_k": 1,
        "repetition_penalty": 1.1,
        "skip_special_tokens": False,
    },
    text_first=True,
)
run, config = runner(PROFILE)
