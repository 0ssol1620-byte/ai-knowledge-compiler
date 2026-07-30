"use client";

import { Line } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { useRef } from "react";
import type { Group } from "three";

function CompilerObject() {
  const group = useRef<Group>(null);

  useFrame((state) => {
    if (!group.current) return;
    const targetX = state.pointer.y * 0.035;
    const targetY = state.pointer.x * 0.045;
    group.current.rotation.x += (targetX - group.current.rotation.x) * 0.045;
    group.current.rotation.y += (targetY - group.current.rotation.y) * 0.045;
  });

  return (
    <group ref={group} rotation={[-0.08, -0.12, 0.015]}>
      {[-0.34, -0.17, 0].map((z, index) => (
        <group key={z} position={[-1.25 + index * 0.12, index * 0.08, z]}>
          <mesh>
            <boxGeometry args={[1.75, 2.35, 0.035]} />
            <meshStandardMaterial color={index === 2 ? "#fcfcfa" : "#e8e7e1"} />
          </mesh>
          {index === 2 && (
            <>
              <mesh position={[0, 0.73, 0.03]}>
                <boxGeometry args={[1.25, 0.14, 0.025]} />
                <meshStandardMaterial color="#20242b" />
              </mesh>
              <mesh position={[0, 0.42, 0.03]}>
                <boxGeometry args={[1.25, 0.035, 0.025]} />
                <meshStandardMaterial color="#a9adb3" />
              </mesh>
              <mesh position={[0, 0.18, 0.03]}>
                <boxGeometry args={[1.25, 0.32, 0.025]} />
                <meshStandardMaterial color="#f1f2ef" />
              </mesh>
              <mesh position={[0, -0.32, 0.03]}>
                <boxGeometry args={[1.25, 0.62, 0.025]} />
                <meshStandardMaterial color="#ffffff" />
              </mesh>
            </>
          )}
        </group>
      ))}

      {[0.72, 0.25, -0.25].map((y, index) => (
        <mesh key={y} position={[-0.1 + index * 0.16, y, 0.38 + index * 0.08]}>
          <boxGeometry args={[0.88, index === 2 ? 0.5 : 0.22, 0.05]} />
          <meshStandardMaterial
            color={
              index === 2 ? "#dff2f4" : index === 1 ? "#e9edfb" : "#ffffff"
            }
          />
        </mesh>
      ))}

      <Line
        points={[
          [0.4, 0.65, 0.47],
          [0.95, 0.5, 0.42],
          [1.2, 0.2, 0.35],
        ]}
        color="#315be8"
        lineWidth={1.35}
      />
      <Line
        points={[
          [0.45, -0.28, 0.52],
          [1.0, -0.22, 0.38],
          [1.35, -0.55, 0.24],
        ]}
        color="#2aa8bd"
        lineWidth={1.35}
      />

      {(
        [
          [1.25, 0.2, 0.35],
          [1.48, -0.1, 0.18],
          [1.38, -0.58, 0.22],
          [1.84, 0.37, -0.06],
          [1.96, -0.29, -0.12],
        ] as const
      ).map(([x, y, z], index) => (
        <mesh key={`${x}-${y}`} position={[x, y, z]}>
          <sphereGeometry args={[index === 0 ? 0.12 : 0.08, 24, 24]} />
          <meshStandardMaterial color={index < 2 ? "#315be8" : "#2aa8bd"} />
        </mesh>
      ))}
      <Line
        points={[
          [1.25, 0.2, 0.35],
          [1.84, 0.37, -0.06],
          [1.96, -0.29, -0.12],
          [1.38, -0.58, 0.22],
          [1.48, -0.1, 0.18],
          [1.25, 0.2, 0.35],
        ]}
        color="#738094"
        lineWidth={0.8}
      />
    </group>
  );
}

export default function StructaraWebglScene() {
  return (
    <Canvas
      dpr={[1, 1.5]}
      camera={{ position: [0, 0, 6], fov: 37 }}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      frameloop="always"
    >
      <ambientLight intensity={1.7} />
      <directionalLight position={[4, 6, 5]} intensity={2.2} color="#ffffff" />
      <directionalLight
        position={[-4, -3, 3]}
        intensity={0.8}
        color="#cbd6ff"
      />
      <CompilerObject />
    </Canvas>
  );
}
