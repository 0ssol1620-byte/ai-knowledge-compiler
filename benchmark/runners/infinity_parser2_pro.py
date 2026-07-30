from .base import RunnerConfig, run_external

PROVIDER = "infinity_parser2_pro"


def run(case, *, endpoint, revision, allow_network=False):
    return run_external(RunnerConfig(PROVIDER, revision, endpoint, allow_network), case)
