from .base import RunnerConfig, run_external

PROVIDER = "paddleocr_vl_1_6"


def run(case, *, endpoint, revision, allow_network=False):
    return run_external(RunnerConfig(PROVIDER, revision, endpoint, allow_network), case)
