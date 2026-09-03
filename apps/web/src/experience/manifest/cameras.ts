/**
 * Camera presets — CINEMATIC_DESIGN_MASTER_SPEC §7.2.
 *
 * Transcribed, not invented. Every value here is founder-locked; changing one
 * changes what a shot means, so a change needs a spec revision, not a commit.
 *
 * World coordinate convention (§7.1): +x right, +y up, +z toward camera.
 * Semantic depth reads source-rear / compiled-front, with time as controlled
 * depth strata.
 */

export type CameraPresetId =
  | 'P0_VOID'
  | 'P1_MESS_NEAR'
  | 'P2_DISCOVER'
  | 'P3_RESOLVE'
  | 'P4_COMPILE_CLOSE'
  | 'P5_WORLD_HERO'
  | 'P6_TRUTH'
  | 'P7_CHANGE'
  | 'P8_IMPACT_WIDE'
  | 'P9_ANSWER'
  | 'P10_EVIDENCE_APPROACH'
  | 'P11_CELL_MACRO'
  | 'P12_PERSONAL_WIDE'
  | 'P13_TEAM_WIDE'
  | 'P14_ENTERPRISE'
  | 'P15_EXPLORE';

export type Vec3 = readonly [x: number, y: number, z: number];

export type CameraPreset = {
  readonly id: CameraPresetId;
  readonly position: Vec3;
  readonly target: Vec3;
  /** Vertical field of view, degrees. */
  readonly fov: number;
  readonly purpose: string;
};

export const CAMERA_PRESETS: Readonly<Record<CameraPresetId, CameraPreset>> = {
  P0_VOID: {
    id: 'P0_VOID',
    position: [0.0, 0.0, 22.0],
    target: [2.8, 0.0, 0.0],
    fov: 33,
    purpose: 'Almost no readable world',
  },
  P1_MESS_NEAR: {
    id: 'P1_MESS_NEAR',
    position: [1.2, 0.1, 17.5],
    target: [3.2, 0.0, 0.0],
    fov: 34,
    purpose: 'Hero sources occupy right/center-right',
  },
  P2_DISCOVER: {
    id: 'P2_DISCOVER',
    position: [2.4, 0.2, 14.6],
    target: [4.0, 0.1, 0.0],
    fov: 34,
    purpose: 'Source surfaces and semantic extraction',
  },
  P3_RESOLVE: {
    id: 'P3_RESOLVE',
    position: [3.4, 0.3, 12.2],
    target: [4.7, 0.2, 0.0],
    fov: 33,
    purpose: 'Identity/version convergence',
  },
  P4_COMPILE_CLOSE: {
    id: 'P4_COMPILE_CLOSE',
    position: [4.0, 0.2, 9.8],
    target: [5.0, 0.2, 0.0],
    fov: 31,
    purpose: 'Compiled Knowledge Object hero',
  },
  P5_WORLD_HERO: {
    id: 'P5_WORLD_HERO',
    position: [0.7, 0.5, 25.0],
    target: [5.4, 0.1, 0.0],
    fov: 38,
    purpose: 'First world reveal',
  },
  P6_TRUTH: {
    id: 'P6_TRUTH',
    position: [3.9, 0.4, 14.0],
    target: [5.3, 0.2, 0.0],
    fov: 34,
    purpose: 'Candidate facts and source states',
  },
  P7_CHANGE: {
    id: 'P7_CHANGE',
    position: [4.4, 0.3, 12.8],
    target: [5.5, 0.2, 0.0],
    fov: 33,
    purpose: 'Source revision close',
  },
  P8_IMPACT_WIDE: {
    id: 'P8_IMPACT_WIDE',
    position: [1.8, 0.7, 20.5],
    target: [5.8, 0.1, 0.0],
    fov: 37,
    purpose: 'Affected and unaffected subgraph together',
  },
  P9_ANSWER: {
    id: 'P9_ANSWER',
    position: [4.3, 0.2, 11.2],
    target: [5.4, 0.1, 0.0],
    fov: 31,
    purpose: 'Current fact hero',
  },
  P10_EVIDENCE_APPROACH: {
    id: 'P10_EVIDENCE_APPROACH',
    position: [5.0, 0.0, 8.0],
    target: [5.6, -0.1, 0.0],
    fov: 29,
    purpose: 'Answer to source document',
  },
  P11_CELL_MACRO: {
    id: 'P11_CELL_MACRO',
    position: [5.55, -0.08, 4.4],
    target: [5.62, -0.08, 0.0],
    fov: 24,
    purpose: 'Exact table cell',
  },
  P12_PERSONAL_WIDE: {
    id: 'P12_PERSONAL_WIDE',
    position: [0.8, 0.6, 25.8],
    target: [5.2, 0.0, 0.0],
    fov: 39,
    purpose: 'Personal world topology',
  },
  P13_TEAM_WIDE: {
    id: 'P13_TEAM_WIDE',
    position: [-1.0, 0.8, 29.0],
    target: [5.4, 0.0, 0.0],
    fov: 40,
    purpose: 'Two worlds and shared boundary',
  },
  P14_ENTERPRISE: {
    id: 'P14_ENTERPRISE',
    position: [-2.5, 1.0, 34.0],
    target: [5.8, 0.0, 0.0],
    fov: 42,
    purpose: 'Organization-scale territories',
  },
  P15_EXPLORE: {
    id: 'P15_EXPLORE',
    position: [0.0, 0.6, 24.0],
    target: [5.5, 0.0, 0.0],
    fov: 38,
    purpose: 'User-controlled start',
  },
} as const;

/**
 * Camera movement limits — §7.4. These are ceilings the rig enforces, not
 * suggestions. Production roll is 0°; there is no unmotivated orbit.
 */
export const CAMERA_LIMITS = {
  heroMoveSeconds: { min: 1.2, max: 3.0 },
  localFocusSeconds: { min: 0.65, max: 1.2 },
  macroEvidenceSeconds: { min: 1.2, max: 2.0 },
  unmotivatedOrbitDegrees: 0,
  pointerParallaxDesktop: { yawDegrees: 1.0, pitchDegrees: 0.6 },
  pointerParallaxMobile: { yawDegrees: 0, pitchDegrees: 0 },
  /** Position units of drift permitted over 6s, only after content settles. */
  idleDriftUnitsPer6s: 0.015,
  springOvershoot: false,
  perpetualBreathingScale: false,
  productionRollDegrees: 0,
} as const;

/** Motion curves — §7.3. Token names are load-bearing in the timeline. */
export const EASING = {
  'ease.reveal': 'cubic-bezier(0.22, 1, 0.36, 1)',
  'ease.camera': 'cubic-bezier(0.16, 1, 0.30, 1)',
  'ease.resolve': 'cubic-bezier(0.40, 0, 0.20, 1)',
  'ease.lock': 'cubic-bezier(0.20, 0.80, 0.20, 1)',
  'ease.diff': 'cubic-bezier(0.55, 0, 0.15, 1)',
  'ease.exit': 'cubic-bezier(0.40, 0, 1, 1)',
} as const;

export type EasingToken = keyof typeof EASING;
