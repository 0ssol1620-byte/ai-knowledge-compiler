export type ScaleEvidenceServerConfig = {
  enabled?: string;
  environment?: string;
  targetRevision?: string;
  fixtureSha256?: string;
};

type ScaleEvidenceEnvironment = Readonly<
  Record<string, string | undefined>
>;

export function scaleEvidenceServerConfig(
  environment: ScaleEvidenceEnvironment,
): ScaleEvidenceServerConfig {
  return {
    enabled: environment.AKC_SCALE_TESTS_ENABLED,
    environment: environment.AKC_SCALE_ENVIRONMENT,
    targetRevision: environment.AKC_DEPLOYMENT_REVISION,
    fixtureSha256: environment.AKC_SCALE_FIXTURE_SHA256,
  };
}
