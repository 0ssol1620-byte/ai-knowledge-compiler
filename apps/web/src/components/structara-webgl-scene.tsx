"use client";

import { Line } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { useRef } from "react";
import type { Group } from "three";

const graphNodes = [
  [0.92, 0.54, 0.34],
  [1.28, 0.72, 0.16],
  [1.58, 0.42, 0.02],
  [1.12, 0.12, 0.28],
  [1.5, 0.02, 0.08],
  [1.86, 0.18, -0.12],
  [0.98, -0.3, 0.34],
  [1.36, -0.42, 0.16],
  [1.76, -0.32, -0.08],
  [2.02, -0.62, -0.18],
  [1.46, -0.78, 0.04],
  [0.94, -0.7, 0.3],
] as const;

const graphEdges = [
  [0, 1],
  [0, 3],
  [1, 2],
  [2, 5],
  [3, 4],
  [3, 6],
  [4, 5],
  [4, 7],
  [5, 8],
  [6, 7],
  [6, 11],
  [7, 8],
  [7, 10],
  [8, 9],
  [9, 10],
  [10, 11],
] as const;

function ease(value: number) {
  const clamped = Math.max(0, Math.min(1, value));
  return clamped * clamped * (3 - 2 * clamped);
}

function CompilerObject() {
  const root = useRef<Group>(null);
  const blocks = useRef<Group>(null);
  const proof = useRef<Group>(null);
  const graph = useRef<Group>(null);

  useFrame((state) => {
    if (!root.current || !blocks.current || !proof.current || !graph.current) {
      return;
    }

    const time = Math.min(state.clock.getElapsedTime(), 6);
    const separate = ease((time - 1.6) / 1.5);
    const verify = ease((time - 3.05) / 0.85);
    const connect = ease((time - 3.75) / 1.45);

    blocks.current.position.x = -0.28 + separate * 0.55;
    blocks.current.position.z = 0.06 + separate * 0.34;
    proof.current.visible = verify > 0.04;
    graph.current.position.x = 0.45 + connect * 0.35;
    graph.current.position.z = -0.12 + connect * 0.18;

    const pointerX = time >= 5.2 ? state.pointer.y * 0.025 : 0;
    const pointerY = time >= 5.2 ? state.pointer.x * 0.03 : 0;
    root.current.rotation.x +=
      (pointerX - 0.08 - root.current.rotation.x) * 0.035;
    root.current.rotation.y +=
      (pointerY - 0.1 - root.current.rotation.y) * 0.035;
  });

  return (
    <group ref={root} rotation={[-0.08, -0.1, 0.012]}>
      <group position={[-1.22, 0, 0]}>
        {[-0.32, -0.16, 0].map((z, index) => (
          <group key={z} position={[index * 0.11, index * 0.07, z]}>
            <mesh>
              <boxGeometry args={[1.7, 2.32, 0.03]} />
              <meshStandardMaterial
                color={index === 2 ? "#fcfcfa" : "#e7e5de"}
                roughness={0.92}
              />
            </mesh>
            {index === 2 && (
              <>
                <mesh position={[-0.12, 0.74, 0.03]}>
                  <boxGeometry args={[1.18, 0.13, 0.022]} />
                  <meshStandardMaterial color="#20242b" roughness={0.88} />
                </mesh>
                <mesh position={[-0.12, 0.46, 0.03]}>
                  <boxGeometry args={[1.18, 0.025, 0.022]} />
                  <meshStandardMaterial color="#a8abb0" />
                </mesh>
                <mesh position={[-0.12, 0.22, 0.03]}>
                  <boxGeometry args={[1.18, 0.3, 0.022]} />
                  <meshStandardMaterial color="#f1f2ef" />
                </mesh>
                <mesh position={[-0.12, -0.35, 0.03]}>
                  <boxGeometry args={[1.18, 0.7, 0.022]} />
                  <meshStandardMaterial color="#ffffff" />
                </mesh>
              </>
            )}
          </group>
        ))}
      </group>

      <group ref={blocks}>
        {[
          [0.7, 0.24, "#ffffff"],
          [0.31, 0.24, "#e9edfb"],
          [-0.18, 0.5, "#dff2f4"],
          [-0.68, 0.26, "#ffffff"],
        ].map(([y, height, color], index) => (
          <mesh key={index} position={[-0.04 + index * 0.07, Number(y), 0]}>
            <boxGeometry args={[0.88, Number(height), 0.045]} />
            <meshStandardMaterial
              color={String(color)}
              roughness={0.78}
              metalness={0}
            />
          </mesh>
        ))}
      </group>

      <group ref={proof}>
        <Line
          points={[
            [0.32, 0.68, 0.43],
            [0.74, 0.64, 0.41],
            [1.02, 0.52, 0.35],
          ]}
          color="#315be8"
          lineWidth={1.35}
        />
        <Line
          points={[
            [0.34, -0.18, 0.45],
            [0.76, -0.16, 0.4],
            [1.12, 0.12, 0.28],
          ]}
          color="#2aa8bd"
          lineWidth={1.45}
        />
        <mesh position={[0.33, -0.18, 0.46]}>
          <boxGeometry args={[0.96, 0.56, 0.012]} />
          <meshBasicMaterial color="#2aa8bd" wireframe />
        </mesh>
      </group>

      <group ref={graph}>
        {graphEdges.map(([from, to]) => (
          <Line
            key={`${from}-${to}`}
            points={[graphNodes[from], graphNodes[to]]}
            color="#738094"
            lineWidth={0.7}
          />
        ))}
        {graphNodes.map(([x, y, z], index) => (
          <mesh key={`${x}-${y}`} position={[x, y, z]}>
            <sphereGeometry args={[index === 3 ? 0.105 : 0.065, 18, 18]} />
            <meshStandardMaterial
              color={
                index === 3
                  ? "#315be8"
                  : index % 3 === 0
                    ? "#2aa8bd"
                    : "#7b8697"
              }
              roughness={0.56}
            />
          </mesh>
        ))}
      </group>
    </group>
  );
}

export default function StructaraWebglScene({
  active = true,
}: {
  active?: boolean;
}) {
  return (
    <Canvas
      dpr={[1, 1.5]}
      camera={{ position: [0, 0, 6], fov: 37 }}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      frameloop={active ? "always" : "never"}
    >
      <ambientLight intensity={1.65} />
      <directionalLight position={[4, 6, 5]} intensity={2.1} color="#ffffff" />
      <directionalLight
        position={[-4, -3, 3]}
        intensity={0.72}
        color="#cbd6ff"
      />
      <CompilerObject />
    </Canvas>
  );
}
