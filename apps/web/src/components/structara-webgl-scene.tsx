"use client";

import { useAnimations } from "@react-three/drei";
import { Canvas, useLoader } from "@react-three/fiber";
import { Suspense, useEffect, useRef } from "react";
import { LoopOnce, type Group } from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

function KnowledgePlaneModel({
  active,
  onSettled,
}: {
  active: boolean;
  onSettled: () => void;
}) {
  const root = useRef<Group>(null);
  const { scene, animations } = useLoader(
    GLTFLoader,
    "/hero/hero-documents-master.glb",
  );
  const { actions } = useAnimations(animations, root);

  useEffect(() => {
    const clips = animations.map((clip) => actions[clip.name]).filter(Boolean);
    clips.forEach((action) => {
      if (!action) return;
      action.reset();
      action.setLoop(LoopOnce, 1);
      action.setEffectiveTimeScale(
        Math.max(action.getClip().duration / 8.2, 1),
      );
      action.clampWhenFinished = true;
      action.play();
    });
    const timer = window.setTimeout(onSettled, 8_250);
    return () => {
      window.clearTimeout(timer);
      clips.forEach((action) => action?.stop());
    };
  }, [actions, animations, onSettled]);

  useEffect(() => {
    Object.values(actions).forEach((action) => {
      if (action) action.paused = !active;
    });
  }, [actions, active]);

  return (
    <group ref={root} rotation={[-0.04, -0.035, 0]} scale={1.06}>
      <primitive object={scene} />
    </group>
  );
}

export default function StructaraWebglScene({
  active = true,
  onSettled,
  onContextFailure,
}: {
  active?: boolean;
  onSettled: () => void;
  onContextFailure: () => void;
}) {
  return (
    <Canvas
      dpr={[1, 1.5]}
      camera={{ position: [0, -8.0, 4.7], fov: 36 }}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      frameloop={active ? "always" : "never"}
      onCreated={({ gl }) => {
        gl.domElement.addEventListener("webglcontextlost", onContextFailure, {
          once: true,
        });
      }}
    >
      <ambientLight intensity={1.35} />
      <directionalLight
        position={[-4, -5, 7]}
        intensity={2.0}
        color="#fffdf7"
      />
      <directionalLight position={[4, 2, 4]} intensity={0.58} color="#cbd6ff" />
      <Suspense fallback={null}>
        <KnowledgePlaneModel active={active} onSettled={onSettled} />
      </Suspense>
    </Canvas>
  );
}
