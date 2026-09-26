# Prompt registry — lane R (was A4)

Frozen prompts for campaign `TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1`. See
`ARENA_CONTRACT.md` §3.9 for the file contract, §11.5 **D17** for the re-key
this directory now implements, and §11.5 **D34** for the `prompt_kind`
vocabulary.

## What changed in the second integration pass (D17)

The first pass keyed everything `<model_key>_official_v1` and recorded what a
model's *documentation* says its prompt is. `runtimes/<model_key>/runtime.json`
declares a different `prompt_id` per model, and the worker (D17) resolves
`/opt/arena/prompt_registry/<prompt_id>.txt` from **runtime.json**, hashes that
file and refuses a run whose `prompt_sha256` differs. So the registry is now
keyed by the runtime.json `prompt_id` and holds **the exact text the adapter
sends, or the text the official toolkit builds at the pinned revision** — not
documentation evidence.

### Retired id → current id

Nothing was deleted silently. These ids no longer appear in `sha256.json` or
`model_specific_prompts.json`; this table is the mapping.

| retired prompt_id (lane A4) | current prompt_id (runtime.json) | text changed? |
|---|---|---|
| `paddleocr_vl_1_6_official_v1` | `paddleocr_vl_1_6_pipeline_internal` | yes — `"OCR:"` → empty (`prompt_kind` `none`) |
| `hpd_parsing_official_v1` | `hpd_parsing_document_parsing_with_fork_v1` | no |
| `mineru_pipeline_official_v1` | `mineru_pipeline_no_prompt` | `null` → empty string |
| `mineru_vlm_official_v1` | `mineru_vlm_no_prompt` | `null` → empty string |
| `deepseek_ocr2_official_v1` | `deepseek_ocr2_grounding_markdown_v1` | no |
| `ovisocr2_official_v1` | `ovisocr2_page_markdown_v1` | **yes** — the leading newline was missing |
| `unlimited_ocr_official_v1` | `unlimited_ocr_document_parsing_v1` | no |
| `infinity_parser2_pro_official_v1` | `infinity_parser2_pro_doc2json_v1` | **yes** — `"doc2md"` token → the model card's doc2json prompt |
| `monkeyocrv2_b_official_v1` | `monkeyocrv2_b_official_pipeline_prompts_v1` | **yes** — `null` → `core_runner.ALL_PROMPT` bundle |
| `olmocr2_official_v1` | `olmocr2_no_anchoring_v4_yaml_v1` | **yes** — anchored `build_finetuning_prompt` → `build_no_anchoring_v4_yaml_prompt` |
| `glm_ocr_official_v1` | `glm_ocr_official_sdk_task_prompts_v1` | **yes** — one token → the SDK `task_prompt_mapping` bundle |

`opus5_transcription_v1` is untouched: the Opus lane has no runtime.json and
`ARENA_CONTRACT.md` §7 names that id directly. Its bytes and sha256 are
byte-identical to the first pass.

## Files

- `<prompt_id>.txt` — one file per runtime.json `prompt_id`, containing the
  prompt bytes **exactly**: UTF-8, no BOM, no added trailing newline, no
  wrapper. A `prompt_kind` `none` model gets a zero-byte file whose sha256 is
  therefore `e3b0c442…b7852b855`, the hash of the empty string.
- `opus5_transcription_v1.txt` — masterplan §21.5 verbatim (16 lines, one
  trailing `\n`).
- `model_specific_prompts.json` — `{prompt_id: {model_key, prompt_id,
  prompt_kind, text, sha256, source_kind, source_url, source_revision,
  source_file, retrieved_at, notes, prompt_bundle?}}`.
- `sha256.json` — `{prompt_id: "sha256:<hex>"}` over the `.txt` file bytes.
  There are no `null` values any more: every declared `prompt_id` resolves.

## `prompt_kind` (D34)

| kind | meaning | worker/adapter rule |
|---|---|---|
| `text` | the adapter sends `AdapterConfig.prompt_text` | text must be non-empty and equal this file |
| `toolkit` | the official toolkit builds the prompt at run time | the adapter hashes what the toolkit built and fails closed against `AdapterConfig.prompt_sha256` |
| `none` | a pipeline that takes no prompt | the file is empty; the adapter refuses a non-empty `prompt_text` |

### Prompt bundles — read this before comparing a hash

Two `toolkit` models do not have *a* page prompt. MonkeyOCRv2-B runs a layout
pass and then recognises each block with that block category's own prompt from
`parsing/core_runner.py::ALL_PROMPT`; GLM-OCR's official SDK runs
PP-DocLayoutV3 and then OCRs each region with a prompt from
`glmocr/config.yaml::pipeline.page_loader.task_prompt_mapping`. For these two
the `.txt` file holds the **`ARENA_CONTRACT.md` §2 canonical JSON** of the
vendor's mapping — `json.dumps(mapping, sort_keys=True,
separators=(",", ":"), ensure_ascii=True)`, no trailing newline. Every key and
value is verbatim from the pinned source; the serialization is the encoding,
not content. `model_specific_prompts.json` additionally carries the mapping as
a `prompt_bundle` object so no consumer has to re-parse the text.

The D34 toolkit check for these two is therefore *"the installed toolkit's
mapping still canonicalises to this sha256"*, not *"the built page prompt
equals this string"*. Lanes C3 (`monkeyocrv2_b`, `glm_ocr`) must use the same
serialization or the hashes will not meet.

## Never-invent rule

Every byte in every `.txt` file was read from an official source at a pinned
revision — a vendor repository file, a Hugging Face model card at a pinned
commit, or an arena adapter constant that itself pins the vendor string's
sha256 at import. Nothing was composed, paraphrased or guessed. Where a model
takes no prompt the file is empty rather than carrying a plausible-looking
instruction.

## Freezing rule (MP §43 — prompts never change mid-run)

Once `arena.controller run --model <key> --execute` has produced the first
`SUCCESS` receipt for that model, the `prompt_id` and `prompt_sha256` bound
into every subsequent `inference_job_id` (§2) for that model are locked. After
that point a change is a **new** `prompt_id` (`…_v2`), never an in-place edit,
because an in-place edit silently changes `inference_job_id` derivation and
breaks the "same id + existing SUCCESS receipt ⇒ never re-run" rule. No model
has run yet, which is why this re-key is still legal.

## Per-model table

| model_key | prompt_id | prompt_kind | source | source_revision |
|---|---|---|---|---|
| `paddleocr_vl_1_6` | `paddleocr_vl_1_6_pipeline_internal` | none | adapter refuses a prompt; the pipeline composes its own internally | — |
| `hpd_parsing` | `hpd_parsing_document_parsing_with_fork_v1` | text | PaddleOCR `HPD-Parsing.en.md` | `1e5aa0ad31bc8a82cd8e1daef7adc24e577d2534` |
| `mineru_pipeline` | `mineru_pipeline_no_prompt` | none | MinerU pipeline backend takes no prompt | `d46c353afc9a401640545c467aca5f19445dc0cf` |
| `mineru_vlm` | `mineru_vlm_no_prompt` | none | MinerU vlm-engine backend takes no prompt | `d46c353afc9a401640545c467aca5f19445dc0cf` |
| `deepseek_ocr2` | `deepseek_ocr2_grounding_markdown_v1` | text | `DeepSeek-OCR2-vllm/config.py::PROMPT` | `bf9c3cce8d31bdcbca4271ef49f124071c0cd77a` |
| `ovisocr2` | `ovisocr2_page_markdown_v1` | text | `ATH-MaaS/OvisOCR2` model card | `1fc9221b7823a371d6e97f92d527cc847e24e107` |
| `unlimited_ocr` | `unlimited_ocr_document_parsing_v1` | text | `baidu/Unlimited-OCR` README | `d49ff64afffc1f47ab563dc1c589bc2f78808fa4` |
| `infinity_parser2_pro` | `infinity_parser2_pro_doc2json_v1` | text | `infly/Infinity-Parser2-Pro` model card | `b27d470100514329fc6439aada8f16ccea5f9e2a` |
| `monkeyocrv2_b` | `monkeyocrv2_b_official_pipeline_prompts_v1` | toolkit (bundle) | `parsing/core_runner.py::ALL_PROMPT` | `d46699fb6a4c71d61588e4a71fce03bff4f1ba33` |
| `olmocr2` | `olmocr2_no_anchoring_v4_yaml_v1` | toolkit | `olmocr/prompts/prompts.py::build_no_anchoring_v4_yaml_prompt` | `1e139a5ea61f1668164e6b63357d7284a8391615` |
| `glm_ocr` | `glm_ocr_official_sdk_task_prompts_v1` | toolkit (bundle) | `glmocr/config.yaml::pipeline.page_loader.task_prompt_mapping` | `98ef9846c7045774ff5391a50139e5cbe2850b54` |
| `opus5_subscription` | `opus5_transcription_v1` | text | masterplan §21.5 | — |
