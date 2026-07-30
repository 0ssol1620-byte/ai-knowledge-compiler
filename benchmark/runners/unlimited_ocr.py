from .base import RunnerConfig, run_external

PROVIDER = "unlimited_ocr"


def run(case, *, endpoint, revision, allow_network=False):
    return run_external(RunnerConfig(PROVIDER, revision, endpoint, allow_network), case)
