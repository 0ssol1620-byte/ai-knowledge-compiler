import { expect, test } from "@playwright/test";

/**
 * The §10 motion contract, asserted in a browser rather than reviewed in CSS.
 *
 * §10.4 defines reduced motion as attenuation, not removal: "정보 손실 0 —
 * 최종 상태를 즉시 표시한다. 감쇠이지 제거가 아니다 (젠틀한 페이드는 유지)."
 * That is a claim about computed values, and computed values are the only
 * place it can be checked. The four legacy blocks this replaced all read as
 * reasonable CSS and all violated it.
 */

test.describe("reduced motion is attenuation, not removal", () => {
  test.use({ contextOptions: { reducedMotion: "reduce" } });

  test("durations clamp to a visible minimum rather than zero", async ({
    page,
  }) => {
    await page.goto("/");

    const probe = await page.evaluate(() => {
      const element = document.createElement("div");
      element.style.transitionProperty = "opacity";
      element.style.transitionDuration = "5s";
      element.style.animationName = "nothing";
      element.style.animationDuration = "5s";
      element.style.animationIterationCount = "infinite";
      document.body.append(element);
      const computed = getComputedStyle(element);
      const result = {
        transition: computed.transitionDuration,
        animation: computed.animationDuration,
        iterations: computed.animationIterationCount,
      };
      element.remove();
      return result;
    });

    // Not zero. A zero here is the removal §10.4 rules out, and is what
    // 0.01ms and 1ms both amounted to.
    expect(probe.transition).not.toBe("0s");
    expect(probe.animation).not.toBe("0s");

    // 90ms — below the threshold where movement reads as travel, above the one
    // where a state change reads as a jump cut.
    expect(probe.transition).toBe("0.09s");
    expect(probe.animation).toBe("0.09s");

    // Loops stop. §10.4 forbids them outright; here even finite repeats
    // collapse to one.
    expect(probe.iterations).toBe("1");
  });

  test("no element is left invisible when motion is reduced", async ({
    page,
  }) => {
    await page.goto("/");
    // The failure mode a JavaScript reveal fallback introduces: content that
    // starts at opacity 0 and is never revealed. Nothing may be transparent
    // and still occupy layout.
    const invisible = await page.evaluate(() =>
      [...document.querySelectorAll<HTMLElement>("main *")].filter((node) => {
        const style = getComputedStyle(node);
        if (style.display === "none" || style.visibility === "hidden") {
          return false;
        }
        const box = node.getBoundingClientRect();
        return style.opacity === "0" && box.width > 0 && box.height > 0;
      }).length,
    );
    expect(invisible).toBe(0);
  });
});

test.describe("typed custom properties", () => {
  test("the facing spread keeps its columns whatever the ratio", async ({
    page,
  }) => {
    await page.goto("/");

    // The ratio is selected by `data-ratio` in CSS rather than written from
    // the component, because a flex value cannot be passed safely through a
    // custom property — @property has no <flex> syntax. An unknown ratio must
    // therefore fall through to the default rule, never to no columns, which
    // is what collapsed this spread once before.
    const probe = await page.evaluate(() => {
      const figure = document.createElement("figure");
      figure.className = "tv-facing";
      figure.dataset.ratio = "not-a-real-ratio";
      figure.style.width = "900px";
      const frame = document.createElement("div");
      frame.className = "tv-facing-frame";
      figure.append(frame);
      document.body.append(figure);
      const columns = getComputedStyle(frame).gridTemplateColumns;
      figure.remove();
      return columns;
    });

    expect(probe).not.toBe("none");
    expect(probe.split(/\s+/).filter(Boolean).length).toBe(3);
  });

  test("the progress property is registered and animatable", async ({
    page,
  }) => {
    await page.goto("/");
    const registered = await page.evaluate(() => {
      const element = document.createElement("div");
      document.body.append(element);
      // An unregistered custom property computes to the literal string it was
      // given. A registered <number> computes to a number, so a garbage value
      // resolves to the initial value instead.
      element.style.setProperty("--tv-progress", "not-a-number");
      const value = getComputedStyle(element).getPropertyValue("--tv-progress");
      element.remove();
      return value.trim();
    });
    expect(registered).toBe("0");
  });
});
