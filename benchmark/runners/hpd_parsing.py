from .base import RunnerConfig, run_external

PROVIDER = "hpd_parsing_1b"


def run(case, *, endpoint, revision, allow_network=False):
    return run_external(RunnerConfig(PROVIDER, revision, endpoint, allow_network), case)
