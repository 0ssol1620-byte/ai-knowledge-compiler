from .base import RunnerConfig, run_external

PROVIDER = "mineru"


def run(case, *, endpoint, revision, allow_network=False):
    return run_external(RunnerConfig(PROVIDER, revision, endpoint, allow_network), case)
