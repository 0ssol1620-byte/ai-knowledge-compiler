import Image from "next/image";

// The WebGL enhancement layer was removed by decision.md G-C (TIER 1 3D is
// dropped; the hero becomes a drop zone in W2). The poster is now the only
// hero render, so it is shown at full opacity.
export function TavonelHeroScene() {
  return (
    <div className="tv-hero-scene">
      <picture className="tv-hero-render">
        <source
          media="(max-width: 640px)"
          srcSet="/hero/TAV-HOME-T2-HERO-EN-MOBILE-1080x1440-v01.avif"
          type="image/avif"
        />
        <source
          media="(max-width: 960px)"
          srcSet="/hero/TAV-HOME-T2-HERO-EN-TABLET-1600x1200-v01.avif"
          type="image/avif"
        />
        <source
          srcSet="/hero/TAV-HOME-T2-HERO-EN-DESKTOP-2880x1800-v01.avif"
          type="image/avif"
        />
        <Image
          src="/hero/TAV-HOME-T2-HERO-EN-DESKTOP-2880x1800-v01.webp"
          alt=""
          width={2880}
          height={1800}
          decoding="async"
          priority
          sizes="(max-width: 640px) 100vw, (max-width: 960px) 92vw, 50vw"
        />
      </picture>
      <small>First-party illustrative model · no generated imagery</small>
    </div>
  );
}
