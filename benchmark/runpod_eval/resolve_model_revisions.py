"""Resolve immutable Hugging Face revisions without downloading model bytes."""

from __future__ import annotations

import argparse
import json

from huggingface_hub import HfApi


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_ids", nargs="+")
    args = parser.parse_args()
    api = HfApi()
    resolved = {
        model_id: api.model_info(model_id).sha for model_id in args.model_ids
    }
    print(json.dumps(resolved, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
