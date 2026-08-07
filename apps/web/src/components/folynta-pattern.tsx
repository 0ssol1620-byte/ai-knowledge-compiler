export type FolyntaPatternName =
  | "page-grid"
  | "semantic-blocks"
  | "evidence-paths"
  | "node-constellation"
  | "coordinate-field"
  | "compilation-layers";

export function FolyntaPattern({
  name,
  className,
}: {
  name: FolyntaPatternName;
  className?: string;
}) {
  return (
    <svg
      className={className}
      viewBox="0 0 1200 640"
      preserveAspectRatio="none"
      aria-hidden="true"
      focusable="false"
      data-pattern={name}
    >
      {name === "page-grid" && (
        <path d="M80 80H1120V560H80ZM80 200H1120M80 320H1120M80 440H1120M320 80V560M600 80V560M880 80V560" />
      )}
      {name === "semantic-blocks" && (
        <>
          <rect x="110" y="92" width="420" height="70" />
          <rect x="110" y="198" width="610" height="126" />
          <rect x="754" y="198" width="330" height="280" />
          <rect x="110" y="360" width="610" height="118" />
        </>
      )}
      {name === "evidence-paths" && (
        <>
          <path d="M90 490C260 490 280 180 470 180S740 420 1110 140" />
          <path d="M90 300C310 300 400 520 650 520S900 260 1110 260" />
          {[90, 470, 650, 1110].map((x, index) => (
            <circle key={x} cx={x} cy={[490, 180, 520, 260][index]} r="7" />
          ))}
        </>
      )}
      {name === "node-constellation" && (
        <>
          <path d="M160 420L360 180 580 330 790 130 1040 380 720 520 580 330 160 420" />
          {[
            [160, 420],
            [360, 180],
            [580, 330],
            [790, 130],
            [1040, 380],
            [720, 520],
          ].map(([x, y]) => (
            <circle key={`${x}-${y}`} cx={x} cy={y} r="10" />
          ))}
        </>
      )}
      {name === "coordinate-field" && (
        <>
          {Array.from({ length: 11 }, (_, index) => (
            <path key={`v-${index}`} d={`M${100 + index * 100} 60V580`} />
          ))}
          {Array.from({ length: 6 }, (_, index) => (
            <path key={`h-${index}`} d={`M60 ${70 + index * 100}H1140`} />
          ))}
          <path d="M220 520L220 360 520 360 520 180 930 180" />
        </>
      )}
      {name === "compilation-layers" && (
        <>
          {[0, 1, 2, 3].map((layer) => (
            <path
              key={layer}
              d={`M${120 + layer * 70} ${470 - layer * 80}L${560 + layer * 70} ${570 - layer * 80}L${1030 + layer * 10} ${390 - layer * 80}L${590 + layer * 10} ${290 - layer * 80}Z`}
            />
          ))}
        </>
      )}
    </svg>
  );
}
