from .base import RunnerConfig, run_external

PROVIDER = "mistral_ocr_4"


def run(case, *, endpoint, revision, allow_network=False):
    return run_external(RunnerConfig(PROVIDER, revision, endpoint, allow_network), case)
