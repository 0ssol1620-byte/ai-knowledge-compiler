from .base import RunnerConfig, run_external

PROVIDER = "deepseek_ocr_2"


def run(case, *, endpoint, revision, allow_network=False):
    return run_external(RunnerConfig(PROVIDER, revision, endpoint, allow_network), case)
