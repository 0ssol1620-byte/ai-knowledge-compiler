from .base import RunnerConfig, run_external

PROVIDER = "olmocr_2"


def run(case, *, endpoint, revision, allow_network=False):
    return run_external(RunnerConfig(PROVIDER, revision, endpoint, allow_network), case)
