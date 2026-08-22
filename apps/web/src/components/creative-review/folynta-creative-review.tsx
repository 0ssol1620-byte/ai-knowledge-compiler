import Link from "next/link";

import styles from "./folynta-creative-review.module.css";

type Direction = "folio" | "axis" | "plane" | "marks";

const directions = [
  { id: "folio", label: "A · Folio Synthesis" },
  { id: "axis", label: "B · Evidence Axis" },
  { id: "plane", label: "C · Compiled Plane" },
  { id: "marks", label: "Symbol studies · 24" },
] as const;

const directionCopy = {
  folio: {
    label: "Direction A · Folio Synthesis",
    title: "Every page finds its place.",
    body: "Reports, spreadsheets, scans, slides, and research become one verified system of knowledge—without losing the route back to source.",
    note: "Diverse sources remain legible while one compiled folio becomes the memory.",
  },
  axis: {
    label: "Direction B · Evidence Axis",
    title: "Structure that proves itself.",
    body: "FOLYNTA compiles the working documents of an organization into typed blocks, evidence routes, and portable knowledge.",
    note: "A measured evidence axis carries each claim from source to reusable output.",
  },
  plane: {
    label: "Direction C · Compiled Plane",
    title: "Knowledge, with the source still inside.",
    body: "A single verified plane keeps document structure, source coordinates, relations, and export-ready knowledge together.",
    note: "The compiled plane is quiet, shallow, and ownable from a single glance.",
  },
} as const;

const sourceTypes = [
  ["Annual report", "PDF", "report"],
  ["Ledger", "XLSX", "ledger"],
  ["Research paper", "PDF", "paper"],
  ["Slide deck", "PPTX", "slides"],
  ["Scanned contract", "SCAN", "scan"],
  ["Policy", "DOCX", "policy"],
  ["Handbook", "EPUB", "book"],
  ["Web article", "HTML", "web"],
  ["Invoice", "PDF", "invoice"],
  ["Chart", "SVG", "chart"],
  ["Form", "PDF", "form"],
  ["Data table", "CSV", "data"],
] as const;

export function FolyntaMark({ index = 0 }: { index?: number }) {
  const family = Math.floor(index / 4) % 6;
  const optical = index % 4;
  const scale = [1, 0.9, 1.06, 0.96][optical] ?? 1;
  const translate = (40 - 40 * scale) / 2;
  const planePaths = [
    "M5 8H29L35 14V32H11L5 26Z",
    "M6 9H19V32H8L4 27V13ZM21 9H33L36 13V27L32 32H21Z",
    "M5 7H35V13L23 22V33H17V22L5 13Z",
    "M5 8H35V15H24V33H16V15H5Z",
    "M7 6H33V34H7V25L13 19L7 13Z",
    "M4 11L17 6L23 12L36 7V29L23 34L17 28L4 33Z",
  ];
  const axisPaths = [
    "M20 9V31M10 20H30",
    "M10 14H30M10 26H30",
    "M20 20V32",
    "M20 10V32M10 14H30",
    "M13 12H28M13 20H28M13 28H28",
    "M10 27L20 20L30 27",
  ];
  const branchPaths = [
    "M11 11L20 20L29 11",
    "M10 14L20 21L30 14",
    "M10 11L20 20L30 11",
    "M12 27L20 20L28 27",
    "M13 12L20 20L28 12",
    "M9 14L17 21M31 13L23 20",
  ];

  return (
    <svg
      viewBox="0 0 40 40"
      role="img"
      aria-label={`FOLYNTA symbol study ${index + 1}`}
    >
      <g transform={`translate(${translate} ${translate}) scale(${scale})`}>
        <path className={styles.markPlane} d={planePaths[family]} />
        <path className={styles.markAxis} d={axisPaths[family]} />
        <path className={styles.markBranch} d={branchPaths[family]} />
        <path
          className={styles.markProof}
          d={`M${27 - optical} 25H34V${29 + optical}`}
        />
      </g>
    </svg>
  );
}

function SourceDiagram({ kind }: { kind: string }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.4 };
  return (
    <svg
      className={styles.sourceDiagram}
      viewBox="0 0 100 76"
      aria-hidden="true"
    >
      {kind === "report" && (
        <>
          <path {...common} d="M16 7H66L84 25V68H16Z" />
          <path {...common} d="M66 7V25H84M27 36H71M27 45H63M27 54H74" />
        </>
      )}
      {kind === "ledger" && (
        <>
          <rect {...common} x="9" y="9" width="82" height="58" />
          <path
            {...common}
            d="M9 25H91M9 41H91M9 55H91M31 9V67M58 9V67M75 9V67"
          />
          <rect
            className={styles.diagramAccent}
            x="59"
            y="42"
            width="15"
            height="12"
          />
        </>
      )}
      {kind === "paper" && (
        <>
          <path {...common} d="M18 6H82V70H18Z" />
          <path
            {...common}
            d="M28 18H72M28 25H61M28 38H46M54 38H72M28 44H46M54 44H72M28 50H46M54 50H72M35 60H65"
          />
          <circle className={styles.diagramAccent} cx="50" cy="60" r="3" />
        </>
      )}
      {kind === "slides" && (
        <>
          <rect {...common} x="7" y="13" width="86" height="50" />
          <rect
            className={styles.diagramAccent}
            x="15"
            y="22"
            width="30"
            height="24"
          />
          <path {...common} d="M53 25H82M53 33H74M53 41H79M25 63V69M75 63V69" />
        </>
      )}
      {kind === "scan" && (
        <>
          <path {...common} d="M20 8L82 14L76 69L14 62Z" />
          <path {...common} d="M25 24L69 28M23 34L71 38M21 44L58 47" />
          <circle {...common} cx="59" cy="54" r="9" />
          <path className={styles.diagramAccentStroke} d="M53 54L58 59L67 49" />
        </>
      )}
      {kind === "policy" && (
        <>
          <path {...common} d="M15 8H85V68H15Z" />
          <path {...common} d="M27 20H68M27 29H75M27 38H66M27 47H75" />
          <path className={styles.diagramAccentStroke} d="M27 58H47M51 58H75" />
        </>
      )}
      {kind === "book" && (
        <>
          <path
            {...common}
            d="M9 13C26 9 39 12 49 20V67C38 59 24 57 9 61ZM91 13C74 9 61 12 51 20V67C62 59 76 57 91 61Z"
          />
          <path {...common} d="M49 20V67M18 25H39M18 34H39M61 25H82M61 34H82" />
        </>
      )}
      {kind === "web" && (
        <>
          <rect {...common} x="7" y="10" width="86" height="56" />
          <path {...common} d="M7 21H93M15 16H18M22 16H25M29 16H32" />
          <rect
            className={styles.diagramAccent}
            x="15"
            y="29"
            width="24"
            height="28"
          />
          <path {...common} d="M47 31H84M47 39H76M47 47H84M47 55H70" />
        </>
      )}
      {kind === "invoice" && (
        <>
          <path
            {...common}
            d="M20 6H80V70L73 65L66 70L59 65L52 70L45 65L38 70L31 65L20 70Z"
          />
          <path
            {...common}
            d="M29 20H70M29 31H48M57 31H70M29 40H48M57 40H70M29 54H70"
          />
          <path className={styles.diagramAccentStroke} d="M49 60H70" />
        </>
      )}
      {kind === "chart" && (
        <>
          <path {...common} d="M13 9V65H91M24 56L42 39L56 48L78 23" />
          <path
            className={styles.diagramAccentStroke}
            d="M24 48L42 31L56 40L78 15"
          />
          <circle className={styles.diagramAccent} cx="78" cy="15" r="3" />
        </>
      )}
      {kind === "form" && (
        <>
          <rect {...common} x="13" y="8" width="74" height="60" />
          <path
            {...common}
            d="M23 20H50M23 31H31V39H23ZM23 49H31V57H23ZM38 35H74M38 53H68"
          />
          <path className={styles.diagramAccentStroke} d="M24 34L27 37L32 30" />
        </>
      )}
      {kind === "data" && (
        <>
          <path
            {...common}
            d="M7 12H93V64H7ZM7 28H93M7 44H93M29 12V64M57 12V64M76 12V64"
          />
          <path
            className={styles.diagramAccentStroke}
            d="M12 36H24M34 52H52M61 20H71"
          />
        </>
      )}
    </svg>
  );
}

function SourceObject({
  name,
  type,
  kind,
  index,
}: {
  name: string;
  type: string;
  kind: string;
  index: number;
}) {
  return (
    <div
      className={styles.sourceObject}
      data-source={index + 1}
      data-kind={kind}
    >
      <span>{type}</span>
      <strong>{name}</strong>
      <SourceDiagram kind={kind} />
    </div>
  );
}

export function SignatureScene({
  direction,
}: {
  direction: Exclude<Direction, "marks">;
}) {
  return (
    <div
      className={styles.signature}
      data-visual={direction}
      aria-hidden="true"
    >
      <div className={styles.sourceField}>
        {sourceTypes.map(([name, type, kind], index) => (
          <SourceObject
            key={name}
            name={name}
            type={type}
            kind={kind}
            index={index}
          />
        ))}
      </div>
      <div className={styles.evidenceRoute}>
        <span />
        <span />
        <span />
      </div>
      <div className={styles.compileCore}>
        <FolyntaMark
          index={direction === "folio" ? 3 : direction === "axis" ? 11 : 19}
        />
        <small>12 sources</small>
        <strong>1 verified folio</strong>
      </div>
      <div className={styles.receipt}>
        <span>Evidence receipt</span>
        <strong>page 13 · cell B7</strong>
        <code>3b7876350a20…</code>
      </div>
    </div>
  );
}

function ReviewNav({ active }: { active: Direction }) {
  return (
    <aside className={styles.reviewNav} aria-label="Creative directions">
      <div>
        <strong>FOLYNTA CREATIVE GATE</strong>
        <span>Static direction · not approved · not product evidence</span>
      </div>
      <nav>
        {directions.map((item) => (
          <Link
            key={item.id}
            href={`/creative-review/folynta-reset?direction=${item.id}`}
            aria-current={active === item.id ? "page" : undefined}
          >
            {item.label}
          </Link>
        ))}
      </nav>
    </aside>
  );
}

function SymbolStudies() {
  return (
    <main id="main-content" className={styles.marksPage}>
      <header>
        <p>FOLYNTA SYMBOL RESET · 24 THUMBNAILS</p>
        <h1>Folio plane. Y branch. T evidence axis. Compiled proof.</h1>
        <span>
          Six geometry families with four optical variations each. These are
          review studies, not an approved logo.
        </span>
      </header>
      <div className={styles.markGrid}>
        {Array.from({ length: 24 }, (_, index) => (
          <article key={index}>
            <FolyntaMark index={index} />
            <div>
              <strong>{String(index + 1).padStart(2, "0")}</strong>
              <span>
                G{Math.floor(index / 4) + 1} · O{(index % 4) + 1}
              </span>
            </div>
          </article>
        ))}
      </div>
      <footer>
        <span>Optical checks: 16px · 24px · 40px · inverse · single color</span>
        <span>Approval required before public brand replacement</span>
      </footer>
    </main>
  );
}

export function FolyntaCreativeReview({ direction }: { direction: Direction }) {
  if (direction === "marks") {
    return (
      <div className={styles.reviewRoot}>
        <ReviewNav active={direction} />
        <SymbolStudies />
      </div>
    );
  }

  const copy = directionCopy[direction];
  return (
    <div className={styles.reviewRoot}>
      <ReviewNav active={direction} />
      <main
        id="main-content"
        className={styles.directionPage}
        data-direction={direction}
      >
        <header className={styles.productNav}>
          <Link href="/" className={styles.wordmark} aria-label="FOLYNTA home">
            <FolyntaMark
              index={direction === "folio" ? 3 : direction === "axis" ? 11 : 19}
            />
            <span>
              <strong>FOLYNTA</strong>
              <small>THE KNOWLEDGE COMPILER</small>
            </span>
          </Link>
          <nav aria-label="Prototype navigation">
            <a href="#platform">Platform</a>
            <a href="#solutions">Solutions</a>
            <a href="#proof">Proof</a>
            <a href="#enterprise">Enterprise</a>
          </nav>
          <div>
            <Link href="/login">Sign in</Link>
            <Link href="/intake">Compile a collection</Link>
          </div>
        </header>
        <section className={styles.hero}>
          <div className={styles.heroCopy}>
            <p>{copy.label}</p>
            <h1>{copy.title}</h1>
            <span>{copy.body}</span>
            <div className={styles.actions}>
              <Link href="/intake">Compile a collection</Link>
              <a href="#proof">Inspect source proof</a>
            </div>
            <small>Source-linked · Portable · Private by policy</small>
          </div>
          <SignatureScene direction={direction} />
        </section>
        <footer className={styles.directionFooter}>
          <p>{copy.note}</p>
          <div>
            <span>PAGE</span>
            <i />
            <span>STRUCTURE</span>
            <i />
            <span>EVIDENCE</span>
            <i />
            <strong>KNOWLEDGE</strong>
          </div>
        </footer>
      </main>
    </div>
  );
}
