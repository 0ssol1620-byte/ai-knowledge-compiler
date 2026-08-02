export type StructaraDiagramDefinition = {
  id: string;
  title: string;
  question: string;
  nodes: readonly string[];
};

export const STRUCTARA_DIAGRAMS = {
  compiler: {
    id: "compiler",
    title: "Source-to-Knowledge Compiler",
    question: "How does a page become usable, source-linked knowledge?",
    nodes: ["Source page", "Typed structure", "Evidence map", "Knowledge"],
  },
  routing: {
    id: "routing",
    title: "Adaptive Routing",
    question: "How does each page receive the right processing path?",
    nodes: ["Page profile", "Native route", "Precision route", "Merge"],
  },
  provenance: {
    id: "provenance",
    title: "Source Provenance",
    question: "How does every result return to its origin?",
    nodes: ["Result", "Block ID", "Page region", "Source file"],
  },
  review: {
    id: "review",
    title: "Autonomous Integrity",
    question: "How are high-risk differences resolved without hiding them?",
    nodes: [
      "Risk signal",
      "Auto repair",
      "Unresolved isolation",
      "Audit event",
    ],
  },
  knowledge: {
    id: "knowledge",
    title: "Knowledge Compilation",
    question: "How do sections become reusable knowledge objects?",
    nodes: ["Sections", "Notes", "Entities", "Relations"],
  },
  vault: {
    id: "vault",
    title: "Obsidian Vault Structure",
    question: "How is compiled knowledge packaged for durable ownership?",
    nodes: ["Markdown notes", "Properties", "Backlinks", "MOC"],
  },
  ontology: {
    id: "ontology",
    title: "Ontology and Graph",
    question: "How does a relation preserve the evidence behind it?",
    nodes: ["Entity", "Relation", "Proof ring", "Perspective"],
  },
  rag: {
    id: "rag",
    title: "RAG Export",
    question: "How does verified structure become retrieval-ready context?",
    nodes: ["Source chunks", "Metadata", "Evidence links", "RAG package"],
  },
  security: {
    id: "security",
    title: "Enterprise Security",
    question: "Where are access and processing policies enforced?",
    nodes: ["Identity", "Project policy", "Worker boundary", "Audit"],
  },
  retention: {
    id: "retention",
    title: "Retention and Purge",
    question: "How does a document leave every processing layer?",
    nodes: ["Retention rule", "Delete request", "Purge jobs", "Proof of purge"],
  },
  dart: {
    id: "dart",
    title: "DART Ground Truth",
    question: "How is a public filing compared with known structure?",
    nodes: ["Public filing", "XBRL facts", "Compiler output", "Evaluator"],
  },
  sec: {
    id: "sec",
    title: "SEC/XBRL Mapping",
    question: "How do Inline XBRL facts remain linked to filing context?",
    nodes: ["SEC filing", "Inline fact", "Context/unit", "Knowledge object"],
  },
} as const satisfies Record<string, StructaraDiagramDefinition>;

export type StructaraDiagramId = keyof typeof STRUCTARA_DIAGRAMS;

export const ROUTE_DIAGRAMS: Partial<Record<string, StructaraDiagramId>> = {
  "/product": "compiler",
  "/product/compile": "compiler",
  "/product/convert": "routing",
  "/product/verify": "provenance",
  "/product/knowledge": "knowledge",
  "/product/graph": "ontology",
  "/product/connect": "rag",
  "/solutions/teams": "review",
  "/solutions/enterprise": "security",
  "/benchmarks": "dart",
  "/security": "retention",
  "/demo/dart": "dart",
  "/demo/sec": "sec",
};
