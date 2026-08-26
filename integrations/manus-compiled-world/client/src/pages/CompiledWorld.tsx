import DashboardLayout from "@/components/DashboardLayout";
import { Progress } from "@/components/ui/progress";
import { trpc } from "@/lib/trpc";
import { startLogin } from "@/const";
import { unzipSync } from "fflate";
import { toast } from "sonner";
import { Archive, ArrowLeft, Check, Cloud, FileUp, FolderOpen, FolderTree, KeyRound, Link2, Loader2, Network, Radio, ScanText, ShieldCheck, Sparkles, UploadCloud, XCircle } from "lucide-react";
import { ChangeEvent, useEffect, useRef, useState } from "react";
import "../world.css";
import "../world-auth.css";
import "../world-connectors.css";
import "../world-drop.css";

const MOVEMENT_STAGES = [
  { id: "intake", label: "Intake", detail: "Source perimeter detected", icon: UploadCloud },
  { id: "scan", label: "Read", detail: "Layout and characters resolving", icon: ScanText },
  { id: "dedupe", label: "Resolve", detail: "Copies and noise separating", icon: Link2 },
  { id: "graph", label: "Compile", detail: "Context architecture forming", icon: Network },
];

const CONNECTOR_OPTIONS = [
  { id: "upload", label: "Direct upload", subline: "Browser → private object store", scope: "READY NOW", boundary: "파일 바이트는 개인 오브젝트 저장소에, 메타데이터는 프로젝트 경계에만 보존됩니다.", icon: UploadCloud },
  { id: "google_drive", label: "Google Drive", subline: "TAVONEL OAuth → Drive read-only", scope: "APPROVAL READY", boundary: "TAVONEL 운영 앱이 고객의 Google Drive 읽기 전용 범위만 요청합니다. 비밀키는 고객에게 보이지 않으며, 원본은 삭제·이동·이름 변경되지 않습니다.", icon: Cloud, provider: "google_drive" as const },
  { id: "sharepoint", label: "SharePoint", subline: "TAVONEL OAuth → Graph read-only", scope: "REGISTRATION NEXT", boundary: "Microsoft Entra 운영 앱이 파일·사이트 읽기 전용 범위만 요청하도록 설계되었습니다. 테넌트 정책이나 관리자 승인이 필요하면 연결 전 그 사실을 명시합니다.", icon: Network, provider: "sharepoint" as const },
  { id: "server", label: "File server", subline: "Customer agent → outbound sync", scope: "CONTROL PLANE", boundary: "사내 파일 서버는 인바운드 포트 개방 없이 고객 환경의 수집 에이전트가 외부로 통신합니다. 현재는 선택 경로·일회성 등록 코드·하트비트·감사만 제공하며, 콘텐츠 수집은 아직 활성화하지 않습니다.", icon: FolderTree },
];

const MAX_FILE_BYTES = 5 * 1024 * 1024;
const MAX_BATCH_BYTES = 18 * 1024 * 1024;
const MAX_ZIP_ENTRIES = 24;
const MAX_ZIP_EXPANDED_BYTES = 16 * 1024 * 1024;

function isZip(file: File) {
  return file.name.toLowerCase().endsWith(".zip") || file.type === "application/zip" || file.type === "application/x-zip-compressed";
}

function detectMime(name: string) {
  const lowered = name.toLowerCase();
  if (lowered.endsWith(".pdf")) return "application/pdf";
  if (lowered.endsWith(".png")) return "image/png";
  if (lowered.endsWith(".jpg") || lowered.endsWith(".jpeg")) return "image/jpeg";
  if (lowered.endsWith(".webp")) return "image/webp";
  if (lowered.endsWith(".txt") || lowered.endsWith(".md") || lowered.endsWith(".csv")) return "text/plain";
  return "application/octet-stream";
}

async function unpackZip(file: File) {
  if (file.size > MAX_FILE_BYTES) throw new Error("Pilot ZIP archives must be 5 MB or smaller.");
  const archive = unzipSync(new Uint8Array(await file.arrayBuffer()));
  const records = Object.entries(archive).filter(([name, bytes]) => !name.endsWith("/") && !name.startsWith("/") && !name.split("/").includes("..") && bytes.length > 0);
  if (!records.length) throw new Error("The ZIP archive does not contain a readable file.");
  if (records.length > MAX_ZIP_ENTRIES) throw new Error(`Pilot ZIP archives may contain up to ${MAX_ZIP_ENTRIES} files.`);
  const expandedSize = records.reduce((total, [, bytes]) => total + bytes.length, 0);
  if (expandedSize > MAX_ZIP_EXPANDED_BYTES) throw new Error("The ZIP archive expands beyond the 16 MB pilot limit.");
  return records.map(([name, bytes]) => new File([bytes], name.replace(/^\/+/, ""), { type: detectMime(name) }));
}

type CompiledResult = {
  sourceName: string;
  duplicateCount: number;
  selection?: "review-selected" | "automatic";
  analysis: { title: string; documentKind: string; summary: string; entities: string[]; directory: string[]; flags: string[]; mode: string };
};

export default function CompiledWorld() {
  return <DashboardLayout><WorldCanvas /></DashboardLayout>;
}

function WorldCanvas() {
  const utils = trpc.useUtils();
  const { data: projects = [], isLoading: projectsLoading } = trpc.world.listProjects.useQuery();
  const [activeProjectId, setActiveProjectId] = useState<number | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [stageIndex, setStageIndex] = useState(0);
  const [runId, setRunId] = useState<number | null>(null);
  const [result, setResult] = useState<CompiledResult | null>(null);
  const [connectorFocus, setConnectorFocus] = useState("upload");
  const [agentName, setAgentName] = useState("");
  const [agentRootsDraft, setAgentRootsDraft] = useState("");
  const [enrollmentCode, setEnrollmentCode] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [ingestProgress, setIngestProgress] = useState<{ current: number; total: number } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const createProject = trpc.world.createProject.useMutation({
    onSuccess: (project) => { setActiveProjectId(project.id); utils.world.listProjects.invalidate(); toast.success("Compiled World opened"); },
    onError: (error) => toast.error(error.message),
  });
  const projectId = activeProjectId ?? projects[0]?.id ?? null;
  const { data: sources = [], isLoading: sourcesLoading } = trpc.world.listSources.useQuery({ projectId: projectId ?? 0 }, { enabled: Boolean(projectId) });
  const { data: latestRun } = trpc.world.latestRun.useQuery({ projectId: projectId ?? 0 }, { enabled: Boolean(projectId) });
  const { data: connections = [] } = trpc.world.connections.list.useQuery({ projectId: projectId ?? 0 }, { enabled: Boolean(projectId) });
  const { data: agentOverview } = trpc.world.connections.agent.overview.useQuery({ projectId: projectId ?? 0 }, { enabled: Boolean(projectId) });
  const upload = trpc.world.uploadSource.useMutation({
    onSuccess: () => { if (projectId) utils.world.listSources.invalidate({ projectId }); toast.success("Source stored in your private world"); },
    onError: (error) => toast.error(error.message),
  });
  const setCanonicalSource = trpc.world.setCanonicalSource.useMutation({
    onSuccess: async () => {
      await utils.world.listProjects.invalidate();
      toast.success("Authority record set for the next compile pass");
    },
    onError: (error) => toast.error(error.message),
  });
  const startConnection = trpc.world.connections.start.useMutation({
    onError: (error) => toast.error(error.message),
  });
  const issueAgentEnrollment = trpc.world.connections.agent.issueEnrollment.useMutation({
    onSuccess: async (response) => {
      setEnrollmentCode(response.enrollmentCode);
      await Promise.all([utils.world.connections.agent.overview.invalidate({ projectId: projectId ?? 0 }), utils.world.connections.list.invalidate({ projectId: projectId ?? 0 })]);
      toast.success("One-time enrollment code issued. File collection remains disabled.");
    },
    onError: (error) => toast.error(error.message),
  });
  const revokeAgent = trpc.world.connections.agent.revoke.useMutation({
    onSuccess: async () => {
      setEnrollmentCode(null);
      await Promise.all([utils.world.connections.agent.overview.invalidate({ projectId: projectId ?? 0 }), utils.world.connections.list.invalidate({ projectId: projectId ?? 0 })]);
      toast.success("Agent enrollment revoked. No customer file was altered.");
    },
    onError: (error) => toast.error(error.message),
  });
  const finishProcessing = (run: { resultJson: string | null }) => {
    try { setResult(JSON.parse(run.resultJson ?? "{}")); } catch { setResult(null); }
    setStageIndex(3); setRunId(null); setIsProcessing(false); toast.success("Compiled context is ready for review");
  };
  const beginCompileMutation = trpc.world.beginCompile.useMutation({
    onSuccess: (run) => { setRunId(run.id); setStageIndex(0); setIsProcessing(true); },
    onError: (error) => { setIsProcessing(false); toast.error(error.message); },
  });
  const advanceCompile = trpc.world.advanceCompile.useMutation({
    onSuccess: (run) => {
      if (run.status === "ready") { finishProcessing(run); return; }
      const nextIndex = MOVEMENT_STAGES.findIndex((stage) => stage.id === run.stage);
      if (nextIndex >= 0) setStageIndex(nextIndex);
    },
    onError: (error) => { setIsProcessing(false); toast.error(error.message); },
  });

  useEffect(() => { if (!activeProjectId && projects[0]) setActiveProjectId(projects[0].id); }, [activeProjectId, projects]);
  useEffect(() => {
    if (!latestRun || isProcessing || result) return;
    if (latestRun.status === "ready" && latestRun.resultJson) {
      try {
        setResult(JSON.parse(latestRun.resultJson));
        setStageIndex(3);
      } catch { setResult(null); }
    }
  }, [isProcessing, latestRun, result]);
  useEffect(() => {
    if (!isProcessing || !runId || advanceCompile.isPending) return;
    const timer = window.setTimeout(() => advanceCompile.mutate({ runId }), 720);
    return () => window.clearTimeout(timer);
  }, [advanceCompile, isProcessing, runId, stageIndex]);

  const progress = isProcessing ? [16, 43, 70, 92][stageIndex] : result ? 100 : 0;
  const activeProject = projects.find((project) => project.id === projectId);
  const activeLabel = isProcessing ? MOVEMENT_STAGES[stageIndex]?.label : result ? "Compiled" : "Awaiting sources";
  const duplicateCount = sources.filter((source) => source.duplicateOfId).length;
  const authoritySources = sources.filter((source) => !source.duplicateOfId);
  const canonicalSourceId = activeProject?.canonicalSourceId ?? null;
  const selectedConnector = CONNECTOR_OPTIONS.find((connector) => connector.id === connectorFocus) ?? CONNECTOR_OPTIONS[0];
  const selectedConnection = "provider" in selectedConnector ? connections.find((connection) => connection.provider === selectedConnector.provider) : undefined;
  const agents = agentOverview?.agents ?? [];
  const auditEvents = agentOverview?.audit ?? [];

  useEffect(() => {
    const input = folderInputRef.current as (HTMLInputElement & { webkitdirectory?: boolean; directory?: boolean }) | null;
    if (!input) return;
    input.webkitdirectory = true;
    input.directory = true;
  }, []);

  const ensureProject = async () => {
    if (projectId) return projectId;
    const project = await createProject.mutateAsync({ name: "First Compiled World" });
    setActiveProjectId(project.id);
    await utils.world.listProjects.invalidate();
    return project.id;
  };

  const ingestFiles = async (candidateFiles: File[]) => {
    const directFiles: File[] = [];
    try {
      for (const file of candidateFiles) {
        if (isZip(file)) directFiles.push(file, ...(await unpackZip(file)));
        else directFiles.push(file);
      }
      if (directFiles.length > MAX_ZIP_ENTRIES + 1) throw new Error(`Pilot intake accepts up to ${MAX_ZIP_ENTRIES} expanded files at a time.`);
      if (directFiles.some((file) => file.size > MAX_FILE_BYTES)) throw new Error("Each pilot source must be 5 MB or smaller.");
      if (directFiles.reduce((total, file) => total + file.size, 0) > MAX_BATCH_BYTES) throw new Error("This intake exceeds the 18 MB pilot batch limit.");
      const id = await ensureProject();
      setIngestProgress({ current: 0, total: directFiles.length });
      for (let index = 0; index < directFiles.length; index += 1) {
        const file = directFiles[index];
        const contentBase64 = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result));
          reader.onerror = () => reject(new Error(`${file.name} could not be read in the browser.`));
          reader.readAsDataURL(file);
        });
        await upload.mutateAsync({ projectId: id, fileName: file.name, mimeType: file.type || detectMime(file.name), contentBase64 });
        setIngestProgress({ current: index + 1, total: directFiles.length });
      }
      await utils.world.listSources.invalidate({ projectId: id });
      toast.success(`${directFiles.length} source${directFiles.length > 1 ? "s" : ""} preserved in your private perimeter.`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "This source batch could not be collected.");
    } finally { setIngestProgress(null); setIsDragging(false); }
  };

  const handleSource = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (files.length) void ingestFiles(files);
  };

  const beginCompile = () => {
    if (!projectId) { createProject.mutate({ name: "First Compiled World" }); return; }
    if (!sources.length) { fileInputRef.current?.click(); return; }
    setResult(null); setStageIndex(0); beginCompileMutation.mutate({ projectId });
  };

  const beginConnectorApproval = async () => {
    const provider = "provider" in selectedConnector ? selectedConnector.provider : undefined;
    if (!provider) return;
    try {
      const id = await ensureProject();
      const response = await startConnection.mutateAsync({ projectId: id, provider });
      await utils.world.connections.list.invalidate({ projectId: id });
      if (!response.configured || !response.authorizationUrl) {
        toast.error("TAVONEL 운영자 OAuth 등록이 아직 완료되지 않았습니다. 고객 비밀키는 필요하지 않습니다.");
        return;
      }
      window.location.assign(response.authorizationUrl);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "이 연결 승인을 시작할 수 없습니다.");
    }
  };

  const beginAgentEnrollment = async () => {
    const roots = agentRootsDraft.split("\n").map((root) => root.trim()).filter(Boolean);
    if (!agentName.trim() || !roots.length) {
      toast.error("Name the agent and add at least one customer-approved root.");
      return;
    }
    const id = await ensureProject();
    await issueAgentEnrollment.mutateAsync({ projectId: id, name: agentName.trim(), scopedRoots: roots });
  };

  const renderAgentControl = () => (
    <div className="agent-control">
      <small><Radio size={12} /> OUTBOUND TLS · HEARTBEAT ONLY · COLLECTION DISABLED</small>
      <p>등록 코드는 선택한 경로와 연결된 한 번의 설치에만 사용됩니다. TAVONEL은 코드의 해시만 보관하며, 이 단계에서는 파일 바이트를 받지 않습니다.</p>
      <label>AGENT LABEL<input value={agentName} onChange={(event) => setAgentName(event.target.value)} placeholder="e.g. Seoul research file server" maxLength={160} /></label>
      <label>APPROVED ROOTS <span>one per line</span><textarea value={agentRootsDraft} onChange={(event) => setAgentRootsDraft(event.target.value)} placeholder={"D:\\Research\\2026\n/volume/knowledge"} rows={2} maxLength={1200} /></label>
      <button className="world-button world-button-connector" type="button" onClick={() => void beginAgentEnrollment()} disabled={issueAgentEnrollment.isPending}>{issueAgentEnrollment.isPending ? <Loader2 size={14} className="spin" /> : <KeyRound size={14} />}Issue one-time enrollment code</button>
      {enrollmentCode && <div className="agent-code"><span>SHOW ONCE / COPY TO CUSTOMER ENVIRONMENT</span><code>{enrollmentCode}</code><small>POST it as a Bearer credential to <b>/api/file-server/heartbeat</b>. No content collection endpoint is enabled.</small></div>}
      {agents.length > 0 && <div className="agent-register">{agents.map((agent) => {
        let roots: string[] = [];
        try { roots = JSON.parse(agent.scopedRootsJson) as string[]; } catch { roots = []; }
        return <article key={agent.id}><div><b>{agent.name}</b><small>{agent.status === "active" ? "HEARTBEAT CONFIRMED" : agent.status === "pending" ? "AWAITING FIRST HEARTBEAT" : agent.status.toUpperCase()}</small><p>{roots.join(" · ")}</p></div>{agent.status !== "revoked" && <button type="button" onClick={() => projectId && revokeAgent.mutate({ projectId, agentId: agent.id })} disabled={revokeAgent.isPending}><XCircle size={13} />Revoke</button>}</article>;
      })}</div>}
      {auditEvents.length > 0 && <div className="agent-audit"><span>AUDIT TRAIL</span>{auditEvents.slice(0, 3).map((event) => <small key={event.id}>{new Date(event.createdAt).toLocaleString()} · {event.eventType.replace(/_/g, " ")}</small>)}</div>}
    </div>
  );

  const projectTitle = activeProject?.name ?? "New Compiled World";
  return (
    <div className="world-shell">
      <header className="world-topbar">
        <a className="world-back" href="/"><ArrowLeft size={15} /> TAVONEL</a>
        <div className="world-title"><span>COMPILED WORLD</span><strong>{projectTitle}</strong></div>
        <div className="world-status"><i /> PRIVATE · SOURCE-BOUND</div>
      </header>

      <main className="world-main">
        <section className="world-intro">
          <div><span className="world-kicker">CUSTOMER PILOT / 01</span><h1>See your sources<br /><em>become a world.</em></h1></div>
          <p>파일을 추가하면 개인 저장소에 보존합니다. TAVONEL은 원문·복사본·추출 구조·제안된 디렉터리의 경계를 화면에 남깁니다.</p>
        </section>

        <section className="world-stage" aria-label="컴파일 작업 공간">
          <div className={`world-constellation ${isProcessing ? "is-running" : ""} ${result ? "is-complete" : ""}`}>
            <div className="world-coordinate coord-a">SOURCE / 001</div><div className="world-coordinate coord-b">PROOF / ON</div><div className="world-coordinate coord-c">SCOPE / PRIVATE</div>
            <div className="world-orbit-line orbit-l1" /><div className="world-orbit-line orbit-l2" /><div className="world-orbit-line orbit-l3" />
            <div className="world-core-node"><small>{activeLabel}</small><strong>{isProcessing ? "READING" : result ? "CONTEXT" : "TAVONEL"}</strong><i /></div>
            {sources.length ? sources.slice(0, 6).map((source, index) => <span className={`source-orb source-orb-${index + 1} ${source.duplicateOfId ? "is-duplicate" : ""}`} key={source.id}><FileUp size={13} /><b>{source.duplicateOfId ? "COPY" : "SOURCE"}</b><small>{source.displayName.slice(0, 17)}</small></span>) : <div className="world-empty-orbit"><UploadCloud size={20} /><span>Drop one source to begin</span></div>}
          </div>

          <div className="world-stage-info">
            <div className="world-stage-head"><span>COMPILE PASS</span><strong>{String(stageIndex + 1).padStart(2, "0")} / 04</strong></div>
            <Progress value={progress} className="world-progress" />
            <div className="world-stage-list">
              {MOVEMENT_STAGES.map((stage, index) => { const Icon = stage.icon; const isCurrent = isProcessing ? index === stageIndex : result ? true : index === 0; return <div className={`movement-stage ${isCurrent ? "is-current" : ""} ${result || index < stageIndex ? "is-done" : ""}`} key={stage.id}><Icon size={16} /><span><b>{stage.label}</b><small>{stage.detail}</small></span>{result || index < stageIndex ? <Check size={15} /> : <i />}</div>; })}
            </div>
          </div>
        </section>

        <section className="world-actions">
          <div className={`intake-panel drop-intake ${isDragging ? "is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setIsDragging(true); }} onDragLeave={() => setIsDragging(false)} onDrop={(event) => { event.preventDefault(); void ingestFiles(Array.from(event.dataTransfer.files)); }}><div className="panel-stamp">SOURCE INTAKE / BATCH READY</div><h2>Bring in a file set.<br />Watch the boundary hold.</h2><p>파일 묶음·ZIP·폴더를 놓으면 원본과 해제된 개별 파일을 함께 보존합니다. 파일 바이트는 SQL이 아닌 개인 오브젝트 저장소에 남습니다.</p><input ref={fileInputRef} className="sr-only" type="file" multiple accept="application/pdf,image/png,image/jpeg,image/webp,text/plain,text/csv,application/zip,.zip" onChange={handleSource} /><input ref={folderInputRef} className="sr-only" type="file" multiple onChange={handleSource} /><div className="drop-ritual"><UploadCloud size={21} /><span>{isDragging ? "Release to preserve this source set" : ingestProgress ? `Preserving ${ingestProgress.current} / ${ingestProgress.total}` : "Drop files, a ZIP, or a folder here"}</span><small>5 MB / source · 18 MB / batch · 24 expanded files</small></div><div className="intake-actions"><button className="world-button world-button-primary" type="button" onClick={() => fileInputRef.current?.click()} disabled={Boolean(ingestProgress)}>{ingestProgress ? <Loader2 size={16} className="spin" /> : <UploadCloud size={16} />}Add files or ZIP</button><button className="world-button world-button-ghost" type="button" onClick={() => folderInputRef.current?.click()} disabled={Boolean(ingestProgress)}><FolderOpen size={16} />Choose folder</button></div></div>
          <div className="connector-panel connector-perimeter">
            <div className="panel-stamp">CONNECTOR PERIMETER</div><h2>Connect with<br />a visible boundary.</h2><p>수집의 편의보다 원본 접근 범위와 권한 경계를 먼저 명시합니다.</p>
            <div className="connector-list">{CONNECTOR_OPTIONS.map((connector) => {
              const Icon = connector.icon;
              const connection = "provider" in connector ? connections.find((item) => item.provider === connector.provider) : undefined;
              const scope = connector.id === "server" && agents.some((agent) => agent.status === "active") ? "HEARTBEAT ACTIVE" : connection?.status === "active" ? "ACTIVE" : connector.scope;
              return <button className={connector.id === connectorFocus ? "is-selected" : ""} type="button" onClick={() => setConnectorFocus(connector.id)} key={connector.id}><Icon size={15} /><span><b>{connector.label}</b><small>{connector.subline}</small></span><em>{scope}</em></button>;
            })}</div>
            <div className="connector-detail"><span>ACCESS CONTRACT</span><p>{selectedConnector.boundary}</p>
              {selectedConnector.id === "server" ? renderAgentControl() : "provider" in selectedConnector && <div className="connector-approval"><small>{selectedConnection?.status === "active" ? "READ-ONLY CONNECTION ACTIVE · NO COLLECTION RUN YET" : selectedConnection?.status === "pending_authorization" ? "AWAITING PROVIDER APPROVAL" : selectedConnection?.status === "error" ? "LAST APPROVAL DID NOT COMPLETE · ORIGINALS UNCHANGED" : "CUSTOMER APPROVES IN THE PROVIDER WINDOW"}</small><button className="world-button world-button-connector" type="button" onClick={() => void beginConnectorApproval()} disabled={startConnection.isPending}>{startConnection.isPending ? <Loader2 size={14} className="spin" /> : <ShieldCheck size={14} />}{selectedConnection?.status === "active" ? "Reconnect read-only scope" : `Approve ${selectedConnector.label}`}</button></div>}
            </div>
          </div>
          <div className="compile-panel"><div className="panel-stamp">EVIDENCE ENGINE</div><h2>Compile what<br />you can inspect.</h2><p>{sources.length ? `${sources.length} source${sources.length > 1 ? "s" : ""} in perimeter · ${duplicateCount} duplicate${duplicateCount === 1 ? "" : "s"} detected` : "No source is in this private perimeter yet."}</p><button className="world-button world-button-compile" type="button" onClick={beginCompile} disabled={isProcessing || beginCompileMutation.isPending || sourcesLoading}>{isProcessing ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}{isProcessing ? "Compiling evidence" : sources.length ? "Compile this world" : "Add a source first"}</button><small>AI-assisted pilot uses gpt-5-mini. Review every proposed result.</small></div>
        </section>

        <section className="world-output" aria-live="polite">
          <div className="output-heading"><div><span className="world-kicker">COMPILED OUTPUT / REVIEW FIRST</span><h2>{result ? "A proposed architecture, never a black box." : "Your compiled architecture appears here."}</h2></div><ShieldCheck size={29} /></div>
          {sources.length > 0 && <div className="authority-review" aria-label="대표 원본 검토"><div><span>AUTHORITY REVIEW</span><p>대표 원본을 정하면 다음 컴파일은 그 원본을 기준으로 제안됩니다. 복사본은 보존되지만 대표로 지정할 수 없습니다.</p></div><div className="authority-list">{authoritySources.map((source) => <button key={source.id} type="button" className={canonicalSourceId === source.id ? "is-authority" : ""} onClick={() => projectId && setCanonicalSource.mutate({ projectId, sourceId: source.id })} disabled={setCanonicalSource.isPending}><span><b>{source.displayName}</b><small>{source.mimeType} · {Math.ceil(source.byteSize / 1024)} KB</small></span><em>{canonicalSourceId === source.id ? "AUTHORITY" : "SELECT"}</em></button>)}</div></div>}
          {result ? <div className="output-grid"><article className="output-source"><span>SOURCE RECORD</span><h3>{result.sourceName}</h3><p>{result.analysis.summary}</p><small>{result.analysis.documentKind} · {result.analysis.mode} · {result.selection === "review-selected" ? "review-selected authority" : "automatic selection"}</small></article><article className="output-directory"><span>PROPOSED DIRECTORY</span><div className="directory-path">{result.analysis.directory.map((node, index) => <span key={`${node}-${index}`}>{index > 0 && <i>/</i>}{node}</span>)}</div><div className="entity-row">{result.analysis.entities.length ? result.analysis.entities.map((entity) => <b key={entity}>{entity}</b>) : <em>Awaiting entity review</em>}</div></article><article className="output-review"><span>REVIEW QUEUE</span><p>{result.duplicateCount ? `${result.duplicateCount} potential duplicate source${result.duplicateCount > 1 ? "s" : ""} retained with a visible copy relationship.` : "No byte-identical duplicate detected in this compile pass."}</p>{result.analysis.flags.map((flag) => <small key={flag}>• {flag}</small>)}</article></div> : <div className="output-empty"><Network size={24} /><p>원문을 추가한 뒤 Compile this world를 누르면, 원본에서 파생된 제안 구조와 검토 큐가 이곳에 남습니다.</p></div>}
        </section>
      </main>
    </div>
  );
}
