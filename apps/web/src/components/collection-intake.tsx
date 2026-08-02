"use client";

import {
  ArrowClockwise,
  CloudSlash,
  FilePlus,
  FolderOpen,
  Pause,
  Play,
  ShieldCheck,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { listProjects } from "@/lib/api-client";
import {
  prepareConnectedCollection,
  controlCollectionUpload,
  type CollectionPreflightResult,
  type CollectionPreparationProgress,
  type ConnectedCollectionResult,
} from "@/lib/collection-client";
import {
  startCollectionProcessing,
  type CollectionOveragePolicy,
} from "@/lib/collection-runtime-client";
import {
  loadLatestCollectionSession,
  restoreCollectionFiles,
  type CollectionFileHandleRecord,
  type CollectionResumeRecord,
} from "@/lib/collection-storage";
import {
  buildIntakeManifest,
  collectionManifestLimitState,
  mergeIntakeFiles,
} from "@/lib/collection-intake";
import {
  filesFromDataTransfer,
  selectDirectoryWithHandle,
  supportsDirectoryPicker,
} from "@/lib/directory-selection";
import {
  formatLocaleNumber,
  localeLanguageTag,
  type StructaraLocale,
} from "@/lib/locale";

type IntakePhase =
  | "collecting"
  | "paused"
  | "local_ready"
  | "connecting"
  | "upload_blocked"
  | "server_preflight_ready"
  | "approving"
  | "processing_started"
  | "error";
type FolderSelectionMode = "append" | "replace";

const DEMO_MODE = process.env.NEXT_PUBLIC_AKC_DEMO_MODE === "true";

const COPY = {
  en: {
    eyebrow: "Collection intake",
    title: "Bring a document collection in without losing its structure",
    intro:
      "Choose a folder or add individual files. FOLYNTA builds a safe local manifest first; no upload, processing job, or credit reservation begins on this screen.",
    boundary: "Local manifest only",
    boundaryBody:
      "A signed server preflight and your approval are required before processing.",
    connectedBoundary: "Authenticated control plane",
    connectedBoundaryBody:
      "Local files use verified browser upload; signed reservation and processing approval remain separately gated.",
    chooseFolder: "Choose folder",
    addFiles: "Add files",
    dropFiles: "Drop a folder or files anywhere in this panel",
    connectCloud: "Cloud sources not connected",
    selectedFolder: "Selected folder files",
    selectedFiles: "Selected files",
    pause: "Pause intake",
    resume: "Resume intake",
    reselect: "Reselect folder",
    clear: "Clear manifest",
    pausedTitle: "Intake is paused",
    pausedBody:
      "The manifest is frozen in this tab. Resume to add files or prepare preflight.",
    ghostTitle: "Folder access is session-bound",
    ghostBody:
      "After a refresh or permission change, reselect the same folder to rebuild the manifest. File paths are never inferred from stale browser state.",
    manifest: "Manifest summary",
    manifestLimit: "Up to 5,000 files · 10 GiB per collection",
    manifestLimitError:
      "This manifest exceeds the 5,000-file or 10 GiB collection boundary. Remove files before connecting it.",
    files: "Accepted files",
    bytes: "Collection size",
    unique: "Unique candidates",
    duplicates: "Possible duplicates",
    rejected: "Unsafe paths rejected",
    duplicateNote:
      "Duplicate candidates are provisional. A content checksum must confirm them during server preflight.",
    formats: "Format distribution",
    paths: "Safe relative paths",
    empty: "Choose a folder or files to build the local manifest.",
    morePaths: (count: number) => `${count} more paths remain in the manifest`,
    estimate: "Reservation ledger",
    estimateIntro:
      "Only evidence-backed values may appear here. Unmeasured estimates stay unavailable.",
    staticLabel: "Static preflight",
    staticEmpty: "Awaiting manifest",
    staticReady: "Ready to request",
    p50: "Sampled P50",
    p95: "Sampled P95",
    maximum: "Maximum reservation",
    notMeasured: "Not measured",
    notReserved: "Not reserved",
    prepare: "Prepare server preflight",
    prepared: "Local preflight request is ready",
    preparedBody:
      "No API call, upload, job, or credit reservation has started. Connect an authenticated workspace to continue.",
    connectedTitle: "Connected collection control plane",
    connectedBody:
      "Select a project. FOLYNTA hashes files locally, writes an immutable plan, uploads only required sources through the verified browser pipeline, binds their receipts, and requests preflight when valid.",
    project: "Project",
    loadingProjects: "Loading accessible projects…",
    noProjects: "No writable project is available.",
    projectError: "Projects could not be loaded from the authenticated API.",
    retry: "Retry",
    collectionName: "Collection name",
    defaultCollectionName: "Untitled knowledge collection",
    connectPlan: "Upload collection and prepare preflight",
    retryCollection: "Resume collection upload",
    connecting: "Preparing the authenticated collection pipeline…",
    uploadBlocked: "Collection upload needs attention",
    progressHashing: "Hashing locally",
    progressPlanning: "Writing immutable plan",
    progressUploading: "Uploading verified sources",
    progressVerifying: "Binding verified receipts",
    progressPreflight: "Requesting repository preflight",
    resumed: "Resumed",
    recoverTitle: "Recoverable intake found",
    recoverBody: "Resume metadata is in IndexedDB. Restore permitted file handles, or reselect the same folder for full-hash verification.",
    recover: "Restore intake",
    recovering: "Restoring…",
    recovered: "File handles restored. The server will verify the immutable manifest before resuming.",
    reselectRecovery: "Stored file permission is unavailable. Reselect the same folder; full SHA-256 must match before reuse.",
    serverPreflight: "Repository preflight completed",
    serverPreflightBody:
      "The server returned a repository-rule estimate. It is not a sampled production quantile, a signed reservation, or approval to process.",
    sampledPreflightBody:
      "The estimate is backed by the stored adaptive sample. Confirm the reservation ceiling and approve the immutable evidence hashes before processing.",
    apiError: "The connected collection request stopped safely",
    collectionId: "Collection ID",
    plannedFiles: "Planned files",
    ruleBasis: "Estimate basis",
    repositoryRule: "Repository rule v1",
    knownPages: "Known pages",
    ruleLower: "Rule lower estimate",
    ruleUpper: "Rule upper estimate",
    preflightHash: "Preflight evidence hash",
    unavailable: "Unavailable",
    creditUnit: "credits",
    start: "Start processing",
    starting: "Reserving credits and starting…",
    approval: "Processing starts only after explicit approval of the sampled estimate and hard cap.",
    approvalTitle: "Approve the processing reservation",
    approvalConsent:
      "I reviewed the sampled estimate, immutable evidence hashes, refund policy, and maximum credit reservation.",
    hardCap: "Maximum credit reservation",
    overagePolicy: "If the maximum is reached",
    stopAtCap: "Stop automatically",
    allowTenPercent: "Allow up to 10% more",
    continueWithinBalance: "Continue on the lowest-cost route within balance",
    sampledRequired: "A sampled-ready estimate is required before approval.",
    invalidHardCap: "The maximum must be at least the recommended reserve ceiling.",
    blueprint: "Knowledge architecture",
    blueprintReason: "Recommendation evidence",
    blueprintRegistry: "Registry hash",
    blueprintModule: "Module hash",
    startError: "Processing could not be started",
  },
  ko: {
    eyebrow: "컬렉션 수집",
    title: "문서 구조를 잃지 않고 컬렉션을 가져오세요",
    intro:
      "폴더 또는 개별 파일을 선택하면 먼저 안전한 로컬 매니페스트를 만듭니다. 이 화면에서는 업로드, 처리 작업, 크레딧 예약이 시작되지 않습니다.",
    boundary: "로컬 매니페스트 전용",
    boundaryBody:
      "처리를 시작하려면 서버가 서명한 사전견적과 사용자의 승인이 필요합니다.",
    connectedBoundary: "인증된 제어 영역",
    connectedBoundaryBody:
      "로컬 파일은 검증된 브라우저 업로드를 사용하며 서명된 예약과 처리 승인은 별도 게이트로 유지됩니다.",
    chooseFolder: "폴더 선택",
    addFiles: "파일 추가",
    dropFiles: "이 영역에 폴더나 파일을 놓으세요",
    connectCloud: "클라우드 소스 미연결",
    selectedFolder: "선택한 폴더 파일",
    selectedFiles: "선택한 파일",
    pause: "수집 일시정지",
    resume: "수집 재개",
    reselect: "폴더 다시 선택",
    clear: "매니페스트 비우기",
    pausedTitle: "수집이 일시정지되었습니다",
    pausedBody:
      "이 탭의 매니페스트가 고정되었습니다. 파일을 추가하거나 사전견적을 준비하려면 재개하세요.",
    ghostTitle: "폴더 접근 권한은 세션에만 유지됩니다",
    ghostBody:
      "새로고침하거나 권한이 바뀌면 같은 폴더를 다시 선택해 매니페스트를 재구성하세요. 오래된 브라우저 상태로 파일 경로를 추정하지 않습니다.",
    manifest: "매니페스트 요약",
    manifestLimit: "컬렉션당 최대 5,000개 파일 · 10 GiB",
    manifestLimitError:
      "이 매니페스트가 파일 5,000개 또는 10 GiB 컬렉션 경계를 넘었습니다. 연결하기 전에 파일을 줄이세요.",
    files: "허용된 파일",
    bytes: "컬렉션 크기",
    unique: "고유 후보",
    duplicates: "중복 가능 후보",
    rejected: "안전하지 않은 경로 제외",
    duplicateNote:
      "중복 표시는 임시 후보입니다. 서버 사전견적 단계에서 콘텐츠 체크섬으로 확인해야 합니다.",
    formats: "형식 분포",
    paths: "안전한 상대 경로",
    empty: "폴더 또는 파일을 선택해 로컬 매니페스트를 만드세요.",
    morePaths: (count: number) => `매니페스트에 경로 ${count}개가 더 있습니다`,
    estimate: "예약 원장",
    estimateIntro:
      "근거가 있는 값만 표시합니다. 측정하지 않은 견적은 비워 둡니다.",
    staticLabel: "정적 사전분석",
    staticEmpty: "매니페스트 대기 중",
    staticReady: "요청 준비됨",
    p50: "샘플 P50",
    p95: "샘플 P95",
    maximum: "최대 예약량",
    notMeasured: "미측정",
    notReserved: "예약 안 됨",
    prepare: "서버 사전견적 준비",
    prepared: "로컬 사전견적 요청이 준비되었습니다",
    preparedBody:
      "API 호출, 업로드, 작업, 크레딧 예약은 시작되지 않았습니다. 인증된 워크스페이스를 연결해야 다음 단계로 갈 수 있습니다.",
    connectedTitle: "연결된 컬렉션 제어 영역",
    connectedBody:
      "프로젝트를 선택하면 파일을 로컬에서 해시하고 변경 불가 계획을 기록한 뒤, 필요한 소스만 검증된 브라우저 경로로 업로드하고 영수증을 연결해 유효할 때 사전분석을 요청합니다.",
    project: "프로젝트",
    loadingProjects: "접근 가능한 프로젝트를 불러오는 중…",
    noProjects: "쓰기 가능한 프로젝트가 없습니다.",
    projectError: "인증 API에서 프로젝트를 불러오지 못했습니다.",
    retry: "다시 시도",
    collectionName: "컬렉션 이름",
    defaultCollectionName: "이름 없는 지식 컬렉션",
    connectPlan: "컬렉션 업로드 및 사전분석 준비",
    retryCollection: "컬렉션 업로드 재개",
    connecting: "인증된 컬렉션 파이프라인을 준비하는 중…",
    uploadBlocked: "컬렉션 업로드를 확인해야 합니다",
    progressHashing: "로컬 해시 계산",
    progressPlanning: "변경 불가 계획 기록",
    progressUploading: "검증 소스 업로드",
    progressVerifying: "검증 영수증 연결",
    progressPreflight: "저장소 사전분석 요청",
    resumed: "재개됨",
    recoverTitle: "복구 가능한 수집 세션이 있습니다",
    recoverBody: "재개 메타데이터는 IndexedDB에 있습니다. 허용된 파일 핸들을 복원하거나 동일 폴더를 다시 선택해 전체 해시를 검증하세요.",
    recover: "수집 복원",
    recovering: "복원 중…",
    recovered: "파일 핸들을 복원했습니다. 재개 전 서버가 불변 매니페스트를 검증합니다.",
    reselectRecovery: "저장된 파일 권한을 사용할 수 없습니다. 동일 폴더를 다시 선택하세요. 전체 SHA-256이 일치해야 재사용됩니다.",
    serverPreflight: "저장소 사전분석 완료",
    serverPreflightBody:
      "서버가 저장소 규칙 기반 견적을 반환했습니다. 샘플링된 운영 분위수, 서명된 예약, 처리 승인이 아닙니다.",
    sampledPreflightBody:
      "저장된 적응형 표본에 근거한 견적입니다. 처리 전에 최대 예약량과 변경 불가 근거 해시를 확인하고 승인하세요.",
    apiError: "연결된 컬렉션 요청이 안전하게 중단되었습니다",
    collectionId: "컬렉션 ID",
    plannedFiles: "계획된 파일",
    ruleBasis: "견적 기준",
    repositoryRule: "저장소 규칙 v1",
    knownPages: "확인된 페이지",
    ruleLower: "규칙 하한 견적",
    ruleUpper: "규칙 상한 견적",
    preflightHash: "사전분석 근거 해시",
    unavailable: "사용 불가",
    creditUnit: "크레딧",
    start: "처리 시작",
    starting: "크레딧을 예약하고 처리를 시작하는 중…",
    approval: "샘플 견적과 최대 한도를 명시적으로 승인한 뒤에만 처리가 시작됩니다.",
    approvalTitle: "처리 예약 승인",
    approvalConsent:
      "샘플 견적, 변경 불가 근거 해시, 환불 정책과 최대 크레딧 예약량을 확인했습니다.",
    hardCap: "최대 크레딧 예약량",
    overagePolicy: "최대치 도달 시",
    stopAtCap: "자동 중단",
    allowTenPercent: "최대 10% 추가 허용",
    continueWithinBalance: "잔액 안에서 최저 비용 경로로 계속",
    sampledRequired: "승인하려면 sampled-ready 견적이 필요합니다.",
    invalidHardCap: "최대치는 권장 예약 상한 이상이어야 합니다.",
    blueprint: "지식 아키텍처",
    blueprintReason: "추천 근거",
    blueprintRegistry: "레지스트리 해시",
    blueprintModule: "모듈 해시",
    startError: "처리를 시작하지 못했습니다",
  },
} as const;

export function CollectionIntake({
  locale,
  connected = !DEMO_MODE,
}: {
  locale: StructaraLocale;
  connected?: boolean;
}) {
  const copy = COPY[locale];
  const router = useRouter();
  const folderInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderSelectionMode = useRef<FolderSelectionMode>("append");
  const [files, setFiles] = useState<File[]>([]);
  const [fileHandles, setFileHandles] = useState<CollectionFileHandleRecord[]>(
    [],
  );
  const [dropActive, setDropActive] = useState(false);
  const [phase, setPhase] = useState<IntakePhase>("collecting");
  const [projectsAttempt, setProjectsAttempt] = useState(0);
  const [projectsState, setProjectsState] = useState<
    "idle" | "loading" | "ready" | "empty" | "error"
  >(connected ? "loading" : "idle");
  const [projects, setProjects] = useState<Array<{ id: string; name: string }>>(
    [],
  );
  const [projectId, setProjectId] = useState("");
  const [collectionName, setCollectionName] = useState<string>(
    copy.defaultCollectionName,
  );
  const [connectedResult, setConnectedResult] =
    useState<ConnectedCollectionResult>();
  const [connectedError, setConnectedError] = useState<string>();
  const [connectedProgress, setConnectedProgress] =
    useState<CollectionPreparationProgress>();
  const [activeSession, setActiveSession] = useState<{
    collectionId: string;
    sourceRootId: string;
    browserResumeToken?: string | null;
  }>();
  const [serverPaused, setServerPaused] = useState(false);
  const [approved, setApproved] = useState(false);
  const [hardCap, setHardCap] = useState("");
  const [overagePolicy, setOveragePolicy] =
    useState<CollectionOveragePolicy>("stop_at_cap");
  const [startError, setStartError] = useState<string>();
  const [selectedBlueprintId, setSelectedBlueprintId] = useState("");
  const [recoveryCandidate, setRecoveryCandidate] = useState<{
    sessionId: string;
    record: CollectionResumeRecord;
  }>();
  const [recoveryRestoring, setRecoveryRestoring] = useState(false);
  const [recoveryNotice, setRecoveryNotice] = useState<string>();
  const recoveryChecked = useRef(new Set<string>());
  const preparationController = useRef<AbortController | undefined>(undefined);
  const manifest = useMemo(() => buildIntakeManifest(files), [files]);
  const manifestLimits = useMemo(
    () => collectionManifestLimitState(manifest),
    [manifest],
  );
  const paused = phase === "paused";
  const connecting = phase === "connecting";
  const approving = phase === "approving";
  const estimate = connectedResult?.preflight?.estimate;
  const selectedBlueprint = estimate?.knowledge_blueprint_candidates.find(
    (candidate) => candidate.id === selectedBlueprintId,
  );
  const approvalReady =
    connected &&
    phase === "server_preflight_ready" &&
    estimate?.status === "sampled_ready" &&
    Boolean(
      selectedBlueprint &&
        /^sha256:[0-9a-f]{64}$/.test(selectedBlueprint.module_sha256),
    ) &&
    approved &&
    (connectedResult?.preflight
      ? validHardCap(connectedResult.preflight, hardCap)
      : false);

  useEffect(
    () => () => {
      preparationController.current?.abort();
    },
    [],
  );

  useEffect(() => {
    const input = folderInputRef.current;
    if (!input) return;
    input.setAttribute("webkitdirectory", "");
    input.setAttribute("directory", "");
  }, []);

  useEffect(() => {
    if (!connected) return;
    let active = true;
    void listProjects()
      .then((rows) => {
        if (!active) return;
        const next = rows.map(({ id, name }) => ({ id, name }));
        setProjects(next);
        setProjectId((current) =>
          next.some((project) => project.id === current)
            ? current
            : (next[0]?.id ?? ""),
        );
        setProjectsState(next.length > 0 ? "ready" : "empty");
      })
      .catch(() => {
        if (!active) return;
        setProjects([]);
        setProjectId("");
        setProjectsState("error");
      });
    return () => {
      active = false;
    };
  }, [connected, projectsAttempt]);

  useEffect(() => {
    if (!connected || !projectId || recoveryChecked.current.has(projectId)) {
      return;
    }
    recoveryChecked.current.add(projectId);
    let active = true;
    void loadLatestCollectionSession(projectId).then((candidate) => {
      if (!active || !candidate) return;
      setRecoveryCandidate(candidate);
      setActiveSession({
        collectionId: candidate.record.collectionId,
        sourceRootId: candidate.record.sourceRootId,
        browserResumeToken: candidate.record.browserResumeToken,
      });
    });
    return () => {
      active = false;
    };
  }, [connected, projectId]);

  function resetConnectedPreparation(preserveSession = false) {
    preparationController.current?.abort();
    preparationController.current = undefined;
    setPhase("collecting");
    setConnectedResult(undefined);
    setConnectedError(undefined);
    setConnectedProgress(undefined);
    if (!preserveSession) setActiveSession(undefined);
    setServerPaused(false);
    setApproved(false);
    setHardCap("");
    setSelectedBlueprintId("");
    setStartError(undefined);
  }

  function acceptFiles(
    next: FileList | readonly File[] | null,
    replace = false,
    handles: readonly CollectionFileHandleRecord[] = [],
  ) {
    if (!next || paused || connecting) return;
    const selected = Array.from(next);
    setFiles((current) =>
      replace ? selected : mergeIntakeFiles(current, selected),
    );
    setFileHandles((current) =>
      replace ? [...handles] : mergeFileHandles(current, handles),
    );
    resetConnectedPreparation(Boolean(recoveryCandidate));
    if (recoveryCandidate) {
      setActiveSession({
        collectionId: recoveryCandidate.record.collectionId,
        sourceRootId: recoveryCandidate.record.sourceRootId,
        browserResumeToken: recoveryCandidate.record.browserResumeToken,
      });
      setRecoveryNotice(copy.reselectRecovery);
    }
  }

  async function restoreLatestIntake(): Promise<void> {
    if (!recoveryCandidate || recoveryRestoring) return;
    setRecoveryRestoring(true);
    setConnectedError(undefined);
    try {
      const restored = await restoreCollectionFiles(recoveryCandidate.sessionId);
      setActiveSession({
        collectionId: recoveryCandidate.record.collectionId,
        sourceRootId: recoveryCandidate.record.sourceRootId,
        browserResumeToken: recoveryCandidate.record.browserResumeToken,
      });
      if (restored.length > 0) {
        setFiles(restored);
        setRecoveryNotice(copy.recovered);
      } else {
        setRecoveryNotice(copy.reselectRecovery);
      }
    } catch (error) {
      setConnectedError(error instanceof Error ? error.message : copy.apiError);
      setPhase("error");
    } finally {
      setRecoveryRestoring(false);
    }
  }

  async function openFolder(mode: FolderSelectionMode) {
    if (paused || connecting) return;
    folderSelectionMode.current = mode;
    if (supportsDirectoryPicker()) {
      try {
        const selection = await selectDirectoryWithHandle();
        if (selection) {
          acceptFiles(selection.files, mode === "replace", selection.handles);
        }
      } catch (error) {
        setConnectedError(error instanceof Error ? error.message : copy.apiError);
        setPhase("error");
      }
      return;
    }
    folderInputRef.current?.click();
  }

  async function connectManifest(resumeOverride = activeSession) {
    if (!connected) {
      setPhase("local_ready");
      return;
    }
    setPhase("connecting");
    setConnectedError(undefined);
    setConnectedProgress(undefined);
    const controller = new AbortController();
    preparationController.current?.abort();
    preparationController.current = controller;
    try {
      const result = await prepareConnectedCollection({
        projectId,
        name: collectionName,
        files,
        fileHandles,
        signal: controller.signal,
        resume:
          resumeOverride ??
          (connectedResult && isResumableBlocker(connectedResult.blocker)
            ? {
                collectionId: connectedResult.collectionId,
                sourceRootId: connectedResult.sourceRootId,
                limitations: connectedResult.limitations,
                browserResumeToken: connectedResult.browserResumeToken,
              }
            : undefined),
        onSession: setActiveSession,
        onProgress: setConnectedProgress,
      });
      setConnectedResult(result);
      if (result.preflight) {
        const nextEstimate = result.preflight.estimate;
        const ceiling = nextEstimate.reserve_ceiling ?? nextEstimate.p95_credits;
        setHardCap(ceiling === null ? "" : String(ceiling));
        setSelectedBlueprintId(nextEstimate.knowledge_blueprint_id);
        setApproved(false);
        setStartError(undefined);
      }
      setRecoveryCandidate(undefined);
      setRecoveryNotice(undefined);
      setPhase(result.blocker ? "upload_blocked" : "server_preflight_ready");
    } catch (error) {
      if (controller.signal.aborted) {
        setPhase("paused");
        return;
      }
      setConnectedError(error instanceof Error ? error.message : copy.apiError);
      setPhase("error");
    } finally {
      if (preparationController.current === controller) {
        preparationController.current = undefined;
      }
    }
  }

  async function toggleIntakePause(): Promise<void> {
    if (!paused) {
      preparationController.current?.abort(
        new DOMException("Collection intake paused", "AbortError"),
      );
      if (connecting && activeSession) {
        try {
          await controlCollectionUpload(activeSession.collectionId, "pause");
          setServerPaused(true);
        } catch (error) {
          setConnectedError(error instanceof Error ? error.message : copy.apiError);
          setPhase("error");
          return;
        }
      }
      setPhase("paused");
      return;
    }
    let resumedSession = activeSession;
    if (serverPaused && activeSession) {
      try {
        const response = await controlCollectionUpload(
          activeSession.collectionId,
          "resume",
          activeSession.browserResumeToken,
        );
        resumedSession = {
          ...activeSession,
          browserResumeToken:
            response.browser_resume_token ?? activeSession.browserResumeToken,
        };
        setActiveSession(resumedSession);
        setServerPaused(false);
      } catch (error) {
        setConnectedError(error instanceof Error ? error.message : copy.apiError);
        setPhase("error");
        return;
      }
    }
    setPhase("collecting");
    if (resumedSession && files.length > 0) {
      void connectManifest(resumedSession);
    }
  }

  async function startProcessing(): Promise<void> {
    const preflight = connectedResult?.preflight;
    const blueprint = preflight?.estimate.knowledge_blueprint_candidates.find(
      (candidate) => candidate.id === selectedBlueprintId,
    );
    if (
      !preflight ||
      !blueprint ||
      !approved ||
      !validHardCap(preflight, hardCap)
    ) {
      return;
    }
    setPhase("approving");
    setStartError(undefined);
    try {
      await startCollectionProcessing({
        collectionId: connectedResult.collectionId,
        preflightSha256: preflight.output_sha256,
        estimateSha256: preflight.estimate.estimate_sha256,
        hardCapCredits: hardCap,
        overagePolicy,
        knowledgeBlueprintId: blueprint.id,
        knowledgeBlueprintRegistrySha256:
          preflight.estimate.knowledge_blueprint_registry_sha256,
        knowledgeBlueprintModuleSha256: blueprint.module_sha256,
        outputModules: preflight.estimate.output_modules,
      });
      setPhase("processing_started");
      router.push(
        `/workspace?collection=${encodeURIComponent(connectedResult.collectionId)}`,
      );
    } catch (error) {
      setStartError(error instanceof Error ? error.message : copy.startError);
      setPhase("server_preflight_ready");
    }
  }

  return (
    <div className="collection-intake-page" data-locale={locale}>
      <header className="collection-intake-heading">
        <div>
          <p>{copy.eyebrow}</p>
          <h1>{copy.title}</h1>
          <span>{copy.intro}</span>
        </div>
        <aside aria-label={connected ? copy.connectedBoundary : copy.boundary}>
          <ShieldCheck size={20} weight="duotone" aria-hidden="true" />
          <span>
            <strong>
              {connected ? copy.connectedBoundary : copy.boundary}
            </strong>
            <small>
              {connected ? copy.connectedBoundaryBody : copy.boundaryBody}
            </small>
          </span>
        </aside>
      </header>

      <section
        className="collection-intake-canvas"
        aria-labelledby="intake-source-title"
        data-drop-active={dropActive}
        onDragEnter={(event) => {
          event.preventDefault();
          if (!paused && !connecting) setDropActive(true);
        }}
        onDragOver={(event) => {
          event.preventDefault();
          event.dataTransfer.dropEffect = paused || connecting ? "none" : "copy";
        }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
            setDropActive(false);
          }
        }}
        onDrop={(event) => {
          event.preventDefault();
          setDropActive(false);
          if (paused || connecting) return;
          void filesFromDataTransfer(event.dataTransfer)
            .then((selection) =>
              acceptFiles(selection.files, false, selection.handles),
            )
            .catch((error: unknown) => {
              setConnectedError(
                error instanceof Error ? error.message : copy.apiError,
              );
              setPhase("error");
            });
        }}
      >
        <header>
          <div>
            <p>01</p>
            <h2 id="intake-source-title">{copy.chooseFolder}</h2>
          </div>
          <div className="collection-intake-actions">
            <button
              type="button"
              onClick={() => void openFolder("append")}
              disabled={paused || connecting}
            >
              <FolderOpen size={18} aria-hidden="true" />
              {copy.chooseFolder}
            </button>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={paused || connecting}
            >
              <FilePlus size={18} aria-hidden="true" />
              {copy.addFiles}
            </button>
            <button
              type="button"
              disabled
              aria-describedby="cloud-source-state"
            >
              <CloudSlash size={18} aria-hidden="true" />
              {copy.connectCloud}
            </button>
          </div>
        </header>
        <p className="collection-drop-hint" aria-hidden="true">
          {copy.dropFiles}
        </p>

        <input
          ref={folderInputRef}
          className="collection-file-input"
          type="file"
          multiple
          disabled={paused || connecting}
          aria-label={copy.selectedFolder}
          data-collection-folder-input
          onChange={(event) => {
            acceptFiles(
              event.currentTarget.files,
              folderSelectionMode.current === "replace",
            );
            event.currentTarget.value = "";
          }}
        />
        <input
          ref={fileInputRef}
          className="collection-file-input"
          type="file"
          multiple
          disabled={paused || connecting}
          aria-label={copy.selectedFiles}
          data-collection-file-input
          onChange={(event) => {
            acceptFiles(event.currentTarget.files);
            event.currentTarget.value = "";
          }}
        />
        <p className="sr-only" id="cloud-source-state">
          {copy.connectCloud}
        </p>

        <div className="collection-control-strip">
          <button
            type="button"
            onClick={() => void toggleIntakePause()}
            disabled={files.length === 0 || approving}
          >
            {paused ? (
              <Play size={17} aria-hidden="true" />
            ) : (
              <Pause size={17} aria-hidden="true" />
            )}
            {paused ? copy.resume : copy.pause}
          </button>
          <button
            type="button"
            onClick={() => void openFolder("replace")}
            disabled={paused}
          >
            <ArrowClockwise size={17} aria-hidden="true" />
            {copy.reselect}
          </button>
          <button
            type="button"
            onClick={() => {
              setFiles([]);
              setFileHandles([]);
              resetConnectedPreparation();
            }}
            disabled={files.length === 0 || connecting}
          >
            {copy.clear}
          </button>
        </div>

        {paused && (
          <div className="collection-intake-state" role="status">
            <strong>{copy.pausedTitle}</strong>
            <span>{copy.pausedBody}</span>
          </div>
        )}

        <div className="collection-ghost-state">
          <FolderOpen size={18} aria-hidden="true" />
          <span>
            <strong>{copy.ghostTitle}</strong>
            <small>{copy.ghostBody}</small>
          </span>
        </div>
        {recoveryCandidate && (
          <div className="collection-recovery-state" role="status">
            <div>
              <strong>{copy.recoverTitle}</strong>
              <span>{recoveryNotice ?? copy.recoverBody}</span>
              <code>{recoveryCandidate.record.collectionId}</code>
            </div>
            <button
              type="button"
              disabled={recoveryRestoring || connecting}
              onClick={() => void restoreLatestIntake()}
            >
              <ArrowClockwise size={16} aria-hidden="true" />
              {recoveryRestoring ? copy.recovering : copy.recover}
            </button>
          </div>
        )}
      </section>

      <div className="collection-intake-grid">
        <section
          className="collection-manifest"
          aria-labelledby="manifest-title"
        >
          <header>
            <p>02</p>
            <h2 id="manifest-title">{copy.manifest}</h2>
            <small className="collection-manifest-limit">
              {copy.manifestLimit}
            </small>
          </header>
          {manifest.accepted.length === 0 && manifest.rejected.length === 0 ? (
            <p className="collection-empty-state">{copy.empty}</p>
          ) : (
            <>
              <dl className="collection-manifest-stats">
                <div>
                  <dt>{copy.files}</dt>
                  <dd>
                    {formatLocaleNumber(locale, manifest.accepted.length)}
                  </dd>
                </div>
                <div>
                  <dt>{copy.bytes}</dt>
                  <dd>{formatBytes(manifest.totalBytes, locale)}</dd>
                </div>
                <div>
                  <dt>{copy.unique}</dt>
                  <dd>
                    {formatLocaleNumber(locale, manifest.uniqueCandidates)}
                  </dd>
                </div>
                <div>
                  <dt>{copy.duplicates}</dt>
                  <dd>
                    {formatLocaleNumber(locale, manifest.duplicateCandidates)}
                  </dd>
                </div>
                <div>
                  <dt>{copy.rejected}</dt>
                  <dd>
                    {formatLocaleNumber(locale, manifest.rejected.length)}
                  </dd>
                </div>
              </dl>
              <p className="collection-duplicate-note">{copy.duplicateNote}</p>
              {!manifestLimits.withinLimits && (
                <p className="collection-manifest-limit-error" role="alert">
                  {copy.manifestLimitError}
                </p>
              )}
              <div className="collection-manifest-detail">
                <div>
                  <h3>{copy.formats}</h3>
                  <ul className="collection-format-list">
                    {manifest.formats.map((format) => (
                      <li key={format.extension}>
                        <span>.{format.extension}</span>
                        <strong>
                          {formatLocaleNumber(locale, format.count)}
                        </strong>
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h3>{copy.paths}</h3>
                  <ol className="collection-path-list">
                    {manifest.accepted.slice(0, 8).map((entry) => (
                      <li
                        key={entry.relativePath}
                        data-duplicate={Boolean(entry.duplicateOf)}
                      >
                        <code>{entry.relativePath}</code>
                      </li>
                    ))}
                  </ol>
                  {manifest.accepted.length > 8 && (
                    <p>{copy.morePaths(manifest.accepted.length - 8)}</p>
                  )}
                </div>
              </div>
            </>
          )}
        </section>

        <section
          className="collection-reservation"
          aria-labelledby="reservation-title"
        >
          <header>
            <p>03</p>
            <h2 id="reservation-title">{copy.estimate}</h2>
            <span>{copy.estimateIntro}</span>
          </header>
          {connected && (
            <section
              className="collection-api-controls"
              aria-labelledby="collection-api-title"
            >
              <header>
                <h3 id="collection-api-title">{copy.connectedTitle}</h3>
                <p>{copy.connectedBody}</p>
              </header>
              {projectsState === "loading" && (
                <p role="status">{copy.loadingProjects}</p>
              )}
              {projectsState === "error" && (
                <div className="collection-api-project-error" role="alert">
                  <span>{copy.projectError}</span>
                  <button
                    type="button"
                    onClick={() => {
                      setProjectsState("loading");
                      setProjectsAttempt((value) => value + 1);
                    }}
                  >
                    {copy.retry}
                  </button>
                </div>
              )}
              {projectsState === "empty" && <p>{copy.noProjects}</p>}
              {(projectsState === "ready" || projectsState === "loading") && (
                <div className="collection-api-fields">
                  <label>
                    <span>{copy.project}</span>
                    <select
                      value={projectId}
                      disabled={projectsState !== "ready" || connecting}
                      onChange={(event) => {
                        setProjectId(event.currentTarget.value);
                        setRecoveryCandidate(undefined);
                        setRecoveryNotice(undefined);
                        resetConnectedPreparation();
                      }}
                    >
                      {projects.map((project) => (
                        <option key={project.id} value={project.id}>
                          {project.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>{copy.collectionName}</span>
                    <input
                      value={collectionName}
                      disabled={connecting}
                      maxLength={240}
                      onChange={(event) => {
                        setCollectionName(event.currentTarget.value);
                        resetConnectedPreparation();
                      }}
                    />
                  </label>
                </div>
              )}
            </section>
          )}
          <dl>
            <div>
              <dt>{copy.staticLabel}</dt>
              <dd>
                {connectedResult?.preflight
                  ? `${formatLocaleNumber(
                      locale,
                      connectedResult.preflight.estimate.known_pages,
                    )} ${copy.knownPages.toLocaleLowerCase()}`
                  : connectedResult?.blocker
                    ? connectedResult.upload.status
                    : manifest.accepted.length > 0
                      ? copy.staticReady
                      : copy.staticEmpty}
              </dd>
            </div>
            <div>
              <dt>{copy.p50}</dt>
              <dd>
                {connectedResult?.preflight?.estimate.status === "sampled_ready"
                  ? formatRuleCredits(
                      connectedResult.preflight.estimate.p50_credits,
                      locale,
                      copy.unavailable,
                      copy.creditUnit,
                    )
                  : copy.notMeasured}
              </dd>
            </div>
            <div>
              <dt>{copy.p95}</dt>
              <dd>
                {connectedResult?.preflight?.estimate.status === "sampled_ready"
                  ? formatRuleCredits(
                      connectedResult.preflight.estimate.p95_credits,
                      locale,
                      copy.unavailable,
                      copy.creditUnit,
                    )
                  : copy.notMeasured}
              </dd>
            </div>
            <div>
              <dt>{copy.maximum}</dt>
              <dd>
                {connectedResult?.preflight?.estimate.status !== "sampled_ready" ||
                connectedResult.preflight.estimate.reserve_ceiling === null ||
                connectedResult.preflight.estimate.reserve_ceiling === undefined
                  ? copy.notReserved
                  : formatRuleCredits(
                      connectedResult.preflight.estimate.reserve_ceiling,
                      locale,
                      copy.unavailable,
                      copy.creditUnit,
                    )}
              </dd>
            </div>
          </dl>
          <button
            type="button"
            className="collection-preflight-button"
            disabled={
              manifest.accepted.length === 0 ||
              !manifestLimits.withinLimits ||
              paused ||
              connecting ||
              (connected &&
                (projectsState !== "ready" ||
                  !projectId ||
                  !collectionName.trim()))
            }
            onClick={() => void connectManifest()}
          >
            {connecting
              ? progressText(copy, connectedProgress, locale)
              : connected
                ? isResumableBlocker(connectedResult?.blocker)
                  ? copy.retryCollection
                  : copy.connectPlan
                : copy.prepare}
          </button>
          {phase === "local_ready" && (
            <div className="collection-preflight-state" role="status">
              <strong>{copy.prepared}</strong>
              <span>{copy.preparedBody}</span>
            </div>
          )}
          {phase === "connecting" && (
            <div className="collection-api-progress" role="status">
              <strong>{progressText(copy, connectedProgress, locale)}</strong>
              {connectedProgress?.currentFile && (
                <code>{connectedProgress.currentFile}</code>
              )}
            </div>
          )}
          {phase === "upload_blocked" && connectedResult?.blocker && (
            <div className="collection-api-blocker" role="alert">
              <strong>{copy.uploadBlocked}</strong>
              <span>{connectedResult.blocker.message}</span>
              <dl>
                <div>
                  <dt>{copy.collectionId}</dt>
                  <dd>
                    <code>{connectedResult.collectionId}</code>
                  </dd>
                </div>
                <div>
                  <dt>{copy.plannedFiles}</dt>
                  <dd>
                    {formatLocaleNumber(
                      locale,
                      connectedResult.plannedFiles.length,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>{copy.unavailable}</dt>
                  <dd>
                    {formatLocaleNumber(
                      locale,
                      connectedResult.blocker.requiredFiles,
                    )}
                  </dd>
                </div>
              </dl>
            </div>
          )}
          {phase === "server_preflight_ready" && connectedResult?.preflight && (
            <div className="collection-server-preflight" role="status">
              <strong>{copy.serverPreflight}</strong>
              <p>
                {connectedResult.preflight.estimate.status === "sampled_ready"
                  ? copy.sampledPreflightBody
                  : copy.serverPreflightBody}
              </p>
              <dl>
                <div>
                  <dt>{copy.ruleBasis}</dt>
                  <dd>{copy.repositoryRule}</dd>
                </div>
                <div>
                  <dt>{copy.knownPages}</dt>
                  <dd>
                    {formatLocaleNumber(
                      locale,
                      connectedResult.preflight.estimate.known_pages,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>{copy.ruleLower}</dt>
                  <dd>
                    {formatRuleCredits(
                      connectedResult.preflight.estimate.p50_credits,
                      locale,
                      copy.unavailable,
                      copy.creditUnit,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>{copy.ruleUpper}</dt>
                  <dd>
                    {formatRuleCredits(
                      connectedResult.preflight.estimate.p95_credits,
                      locale,
                      copy.unavailable,
                      copy.creditUnit,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>{copy.preflightHash}</dt>
                  <dd>
                    <code>{connectedResult.preflight.output_sha256}</code>
                  </dd>
                </div>
              </dl>
              {connectedResult.preflight.estimate.warnings.map((warning) => (
                <small key={warning}>{warning}</small>
              ))}
            </div>
          )}
          {phase === "error" && connectedError && (
            <div className="collection-api-error" role="alert">
              <strong>{copy.apiError}</strong>
              <span>{connectedError}</span>
            </div>
          )}
          {connectedResult?.preflight && (
            <fieldset
              className="collection-processing-approval"
              disabled={approving || estimate?.status !== "sampled_ready"}
            >
              <legend>{copy.approvalTitle}</legend>
              <label>
                <span>{copy.blueprint}</span>
                <select
                  value={selectedBlueprintId}
                  onChange={(event) => {
                    setSelectedBlueprintId(event.currentTarget.value);
                    setApproved(false);
                  }}
                >
                  {estimate?.knowledge_blueprint_candidates.map((candidate) => (
                    <option key={candidate.id} value={candidate.id}>
                      {candidate.id}
                    </option>
                  ))}
                </select>
              </label>
              <dl className="collection-blueprint-evidence">
                <div>
                  <dt>{copy.blueprintReason}</dt>
                  <dd>
                    {estimate?.knowledge_blueprint_rationale_codes.join(", ") ||
                      copy.unavailable}
                  </dd>
                </div>
                <div>
                  <dt>{copy.blueprintRegistry}</dt>
                  <dd>
                    <code>
                      {estimate?.knowledge_blueprint_registry_sha256 ??
                        copy.unavailable}
                    </code>
                  </dd>
                </div>
                <div>
                  <dt>{copy.blueprintModule}</dt>
                  <dd>
                    <code>{selectedBlueprint?.module_sha256 ?? copy.unavailable}</code>
                  </dd>
                </div>
              </dl>
              <div className="collection-approval-fields">
                <label>
                  <span>{copy.hardCap}</span>
                  <input
                    type="number"
                    inputMode="decimal"
                    min={String(estimate?.reserve_ceiling ?? estimate?.p95_credits ?? 0)}
                    step="0.001"
                    value={hardCap}
                    onChange={(event) => {
                      setHardCap(event.currentTarget.value);
                      setApproved(false);
                    }}
                  />
                </label>
                <label>
                  <span>{copy.overagePolicy}</span>
                  <select
                    value={overagePolicy}
                    onChange={(event) => {
                      setOveragePolicy(
                        event.currentTarget.value as CollectionOveragePolicy,
                      );
                      setApproved(false);
                    }}
                  >
                    <option value="stop_at_cap">{copy.stopAtCap}</option>
                    <option value="allow_10_percent">{copy.allowTenPercent}</option>
                    <option value="continue_within_balance">
                      {copy.continueWithinBalance}
                    </option>
                  </select>
                </label>
              </div>
              {estimate?.status !== "sampled_ready" && (
                <p className="collection-approval-warning" role="status">
                  {copy.sampledRequired}
                </p>
              )}
              {estimate?.status === "sampled_ready" &&
                !validHardCap(connectedResult.preflight, hardCap) && (
                  <p className="collection-approval-warning" role="alert">
                    {copy.invalidHardCap}
                  </p>
                )}
              <label className="collection-approval-consent">
                <input
                  type="checkbox"
                  checked={approved}
                  onChange={(event) => setApproved(event.currentTarget.checked)}
                />
                <span>{copy.approvalConsent}</span>
              </label>
            </fieldset>
          )}
          {startError && (
            <div className="collection-api-error" role="alert">
              <strong>{copy.startError}</strong>
              <span>{startError}</span>
            </div>
          )}
          <button
            type="button"
            className="collection-start-button"
            disabled={!approvalReady || approving}
            aria-busy={approving}
            onClick={() => void startProcessing()}
          >
            {approving ? copy.starting : copy.start}
          </button>
          <small className="collection-approval-note">{copy.approval}</small>
        </section>
      </div>
    </div>
  );
}

type IntakeCopy = (typeof COPY)[StructaraLocale];

function mergeFileHandles(
  current: readonly CollectionFileHandleRecord[],
  incoming: readonly CollectionFileHandleRecord[],
): CollectionFileHandleRecord[] {
  const byPath = new Map(current.map((item) => [item.relativePath, item]));
  for (const item of incoming) byPath.set(item.relativePath, item);
  return [...byPath.values()];
}

function isResumableBlocker(
  blocker: ConnectedCollectionResult["blocker"] | undefined,
): boolean {
  return (
    blocker !== undefined &&
    [
      "SOURCE_UPLOAD_INTERRUPTED",
      "COLLECTION_RECEIPT_BINDING_INTERRUPTED",
      "COLLECTION_UPLOAD_INCOMPLETE",
      "PREFLIGHT_NOT_READY",
    ].includes(blocker.code)
  );
}

function validHardCap(
  preflight: CollectionPreflightResult,
  hardCap: string,
): boolean {
  const estimate = preflight.estimate;
  if (estimate.status !== "sampled_ready") return false;
  if (!/^[0-9a-f]{64}$/.test(preflight.output_sha256)) return false;
  if (!/^[0-9a-f]{64}$/.test(estimate.estimate_sha256)) return false;
  if (!/^sha256:[0-9a-f]{64}$/.test(estimate.knowledge_blueprint_registry_sha256)) {
    return false;
  }
  if (estimate.output_modules.length === 0) return false;
  const parsed = Number(hardCap);
  const requiredValue = estimate.reserve_ceiling ?? estimate.p95_credits;
  if (requiredValue === null) return false;
  const required = Number(requiredValue);
  return (
    hardCap.trim().length > 0 &&
    Number.isFinite(parsed) &&
    parsed >= 0 &&
    Number.isFinite(required) &&
    required >= 0 &&
    parsed >= required
  );
}

function progressText(
  copy: IntakeCopy,
  progress: CollectionPreparationProgress | undefined,
  locale: StructaraLocale,
): string {
  if (!progress) return copy.connecting;
  const label = {
    hashing: copy.progressHashing,
    planning: copy.progressPlanning,
    uploading: copy.progressUploading,
    verifying: copy.progressVerifying,
    preflight: copy.progressPreflight,
  }[progress.stage];
  const count =
    progress.totalFiles > 0
      ? ` · ${formatLocaleNumber(locale, progress.completedFiles)}/${formatLocaleNumber(locale, progress.totalFiles)}`
      : "";
  return `${label}${count}${progress.resumed ? ` · ${copy.resumed}` : ""}`;
}

function formatBytes(bytes: number, locale: StructaraLocale): string {
  if (bytes < 1024) return `${formatLocaleNumber(locale, bytes)} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${new Intl.NumberFormat(localeLanguageTag(locale), {
    maximumFractionDigits: value >= 10 ? 1 : 2,
  }).format(value)} ${units[index]}`;
}

function formatRuleCredits(
  value: string | number | null,
  locale: StructaraLocale,
  unavailable: string,
  creditUnit: string,
): string {
  if (value === null) return unavailable;
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return unavailable;
  return `${formatLocaleNumber(locale, numeric, {
    maximumFractionDigits: 3,
  })} ${creditUnit}`;
}
