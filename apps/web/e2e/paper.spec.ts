import { expect, test } from "@playwright/test";

/**
 * §15.3 paper grain, checked as behaviour rather than by eye.
 *
 * §15.3 does not describe a look, it lists three things the grain has to do,
 * and a grain that fails any of them reads as noise. All three are computable,
 * so none of them needs a screenshot to review.
 */

const SHEET = `
  <div class="tv-paper" data-surface="recto" id="recto"></div>
  <div class="tv-paper" data-surface="recessed" id="recessed"></div>
  <div class="tv-instrument"><div class="tv-paper" id="instrument"></div></div>
`;

test.describe("§15.3 grain", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/design/slop");
    await page.evaluate((markup) => {
      const host = document.createElement("div");
      host.id = "probe";
      host.innerHTML = markup;
      document.body.append(host);
    }, SHEET);
  });

  test("(1) intensity varies with lightness", async ({ page }) => {
    const [lightest, deepest] = await page.evaluate(() =>
      ["recto", "recessed"].map(
        (id) => getComputedStyle(document.getElementById(id)!, "::after").opacity,
      ),
    );
    // The fibre shows as micro-shadow, so it is strongest on the lightest step.
    expect(Number(lightest)).toBeGreaterThan(Number(deepest));
    expect(Number(deepest)).toBeGreaterThan(0);
  });

  test("(3) it disappears on INSTRUMENT", async ({ page }) => {
    const content = await page.evaluate(
      () =>
        getComputedStyle(document.getElementById("instrument")!, "::after")
          .content,
    );
    // Not a lower value — absent. §5.1 makes the material boundary a hard cut,
    // and a grain carried across it would soften the edge that carries meaning.
    expect(content).toBe("none");
  });

  test("(2) magnification does not reveal a grid", async ({ page }) => {
    /*
     * The mechanism, tested directly rather than through a screenshot.
     *
     * A bitmap enlarged five times is interpolated: neighbouring pixels are
     * averaged, so its variance collapses. An SVG filter is re-evaluated at
     * whatever size it is asked for, so its variance is scale-independent.
     * Drawing the grain's own data URI onto a canvas at two sizes and
     * comparing the spread distinguishes the two without a golden image and
     * without an image library in the test process.
     */
    const measured = await page.evaluate(async () => {
      const url = getComputedStyle(document.getElementById("recto")!, "::after")
        .backgroundImage.slice(5, -2)
        .replaceAll('\\"', '"');

      const spreadAt = async (size: number) => {
        const image = new Image();
        image.decoding = "sync";
        await new Promise<void>((resolve, reject) => {
          image.onload = () => resolve();
          image.onerror = () => reject(new Error("grain image failed to load"));
          image.src = url;
        });
        const canvas = document.createElement("canvas");
        canvas.width = size;
        canvas.height = size;
        const context = canvas.getContext("2d", { willReadFrequently: true })!;
        // Nearest-neighbour would hide interpolation; leave smoothing on so a
        // raster source would genuinely blur.
        context.drawImage(image, 0, 0, size, size);
        const { data } = context.getImageData(0, 0, size, size);
        let sum = 0;
        let squares = 0;
        const count = data.length / 4;
        for (let i = 0; i < data.length; i += 4) {
          const value = data[i] ?? 0;
          sum += value;
          squares += value * value;
        }
        const mean = sum / count;
        return Math.sqrt(squares / count - mean * mean);
      };

      return { small: await spreadAt(200), large: await spreadAt(1000) };
    });

    expect(measured.small).toBeGreaterThan(1);
    // Scale-independent within a wide tolerance. An enlarged bitmap would sit
    // far below this; the point is the collapse, not a precise ratio.
    expect(measured.large).toBeGreaterThan(measured.small * 0.6);
  });

  test("the grain layer never intercepts input", async ({ page }) => {
    const events = await page.evaluate(
      () =>
        getComputedStyle(document.getElementById("recto")!, "::after")
          .pointerEvents,
    );
    expect(events).toBe("none");
  });
});
