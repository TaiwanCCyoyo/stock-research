import assert from "node:assert/strict";
import test from "node:test";
import {
    DEFAULT_CAMERA,
    fitBoundsCamera,
    gestureCamera,
    frameFor,
    stepZoom,
    isDefaultCamera,
    wheelZoomFactor,
    zoomCameraAt,
    type Camera,
    type ScreenPoint,
    type Viewport,
} from "./camera.ts";

const viewport = { width: 1000, height: 620 };
const close = (actual: number, expected: number) =>
    assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} != ${expected}`);

function worldAt(
    camera: Camera,
    point: ScreenPoint,
    size: Viewport = viewport,
) {
    const pixelsPerUnit =
        Math.min(size.width / 1000, size.height / 620) * camera.zoom;
    return {
        x: camera.x + (point.x - size.width / 2) / pixelsPerUnit,
        y: camera.y + (point.y - size.height / 2) / pixelsPerUnit,
    };
}

test("ordinary wheel scroll remains a page action; modified wheel normalizes input units", () => {
    const event = { ctrlKey: false, metaKey: false, deltaY: 16, deltaMode: 0 };
    assert.equal(wheelZoomFactor(event, 620), null);
    const pixel = wheelZoomFactor({ ...event, ctrlKey: true }, 620)!;
    const line = wheelZoomFactor(
        { ...event, metaKey: true, deltaY: 1, deltaMode: 1 },
        620,
    )!;
    const page = wheelZoomFactor(
        { ...event, ctrlKey: true, deltaY: 1, deltaMode: 2 },
        16,
    )!;
    close(pixel, line);
    close(pixel, page);
    assert.ok(pixel < 1);
    assert.ok(
        wheelZoomFactor({ ...event, ctrlKey: true, deltaY: -16 }, 620)! > 1,
    );
    assert.equal(
        wheelZoomFactor({ ...event, ctrlKey: true, deltaY: 0 }, 620),
        null,
    );
    assert.equal(
        wheelZoomFactor({ ...event, ctrlKey: true, deltaY: NaN }, 620),
        null,
    );
});

test("pointer-centered zoom preserves the world point and reverses without camera drift", () => {
    const camera = { x: 75, y: -30, zoom: 1.5 };
    const anchor = { x: 800, y: 180 };
    const before = worldAt(camera, anchor);
    const enlarged = zoomCameraAt(camera, 2, viewport, anchor);
    const after = worldAt(enlarged, anchor);
    close(after.x, before.x);
    close(after.y, before.y);
    const restored = zoomCameraAt(enlarged, 0.5, viewport, anchor);
    close(restored.x, camera.x);
    close(restored.y, camera.y);
    close(restored.zoom, camera.zoom);
    assert.deepEqual(camera, { x: 75, y: -30, zoom: 1.5 });
});

test("one pointer moves the map with the finger at the current zoom", () => {
    const camera = { x: 40, y: -20, zoom: 2 };
    const next = gestureCamera(
        camera,
        [{ x: 200, y: 180 }],
        [{ x: 260, y: 160 }],
        viewport,
    );
    assert.deepEqual(next, { x: 10, y: -10, zoom: 2 });
});

test("pinch combines distance zoom with midpoint translation", () => {
    const camera = { x: 30, y: 15, zoom: 1 };
    const previous = [
        { x: 300, y: 200 },
        { x: 500, y: 200 },
    ];
    const current = [
        { x: 250, y: 240 },
        { x: 650, y: 240 },
    ];
    const before = worldAt(camera, { x: 400, y: 200 });
    const next = gestureCamera(camera, previous, current, viewport);
    const after = worldAt(next, { x: 450, y: 240 });
    assert.equal(next.zoom, 2);
    close(after.x, before.x);
    close(after.y, before.y);
});

test("mobile letterboxing uses the SVG rendered scale for both pan and zoom", () => {
    const mobile = { width: 360, height: 330 };
    const moved = gestureCamera(
        DEFAULT_CAMERA,
        [{ x: 100, y: 100 }],
        [{ x: 136, y: 118 }],
        mobile,
    );
    close(moved.x, -100);
    close(moved.y, -50);
    const anchor = { x: 250, y: 210 };
    const before = worldAt(moved, anchor, mobile);
    const enlarged = zoomCameraAt(moved, 1.4, mobile, anchor);
    const after = worldAt(enlarged, anchor, mobile);
    close(after.x, before.x);
    close(after.y, before.y);
});

test("zoom limits retain the pointer anchor instead of moving it at a clamp", () => {
    const anchor = { x: 100, y: 70 };
    const before = worldAt(DEFAULT_CAMERA, anchor);
    for (const [factor, expectedZoom] of [
        [1000, 8],
        [0.0001, 0.01],
    ]) {
        const next = zoomCameraAt(DEFAULT_CAMERA, factor, viewport, anchor);
        assert.equal(next.zoom, expectedZoom);
        const after = worldAt(next, anchor);
        close(after.x, before.x);
        close(after.y, before.y);
    }
});

test("missing pointers and zero-size viewports are safe; coincident fingers can still pan", () => {
    assert.equal(
        gestureCamera(DEFAULT_CAMERA, [], [], viewport),
        DEFAULT_CAMERA,
    );
    assert.equal(
        zoomCameraAt(DEFAULT_CAMERA, 2, { width: 0, height: 0 }),
        DEFAULT_CAMERA,
    );
    assert.equal(
        zoomCameraAt(DEFAULT_CAMERA, Infinity, viewport),
        DEFAULT_CAMERA,
    );
    const next = gestureCamera(
        DEFAULT_CAMERA,
        [
            { x: 100, y: 100 },
            { x: 100, y: 100 },
        ],
        [
            { x: 120, y: 130 },
            { x: 120, y: 130 },
        ],
        viewport,
    );
    assert.deepEqual(next, { x: -20, y: -30, zoom: 1 });
});

test("reset visibility recognizes changed pan or zoom but tolerates rounding noise", () => {
    assert.equal(isDefaultCamera(DEFAULT_CAMERA), true);
    assert.equal(
        isDefaultCamera({ x: 1e-10, y: -1e-10, zoom: 1 + 1e-10 }),
        true,
    );
    assert.equal(isDefaultCamera({ ...DEFAULT_CAMERA, x: 20 }), false);
    assert.equal(isDefaultCamera({ ...DEFAULT_CAMERA, y: -20 }), false);
    assert.equal(isDefaultCamera({ ...DEFAULT_CAMERA, zoom: 2 }), false);
    assert.equal(isDefaultCamera({ ...DEFAULT_CAMERA }), true);
});

test("explicit overview centers distant full-market bounds with padding below the old zoom limit", () => {
    const bounds = { minX: -19000, maxX: 21000, minY: -6000, maxY: 4000 };
    const original = structuredClone(bounds);
    const fit = fitBoundsCamera(bounds);
    close(fit.x, 1000);
    close(fit.y, -1000);
    close(fit.zoom, 0.0225);
    assert.ok(fit.zoom < 0.125);
    for (const x of [bounds.minX, bounds.maxX])
        assert.ok(Math.abs(x - fit.x) * fit.zoom <= 450 + 1e-9);
    for (const y of [bounds.minY, bounds.maxY])
        assert.ok(Math.abs(y - fit.y) * fit.zoom <= 279 + 1e-9);
    assert.deepEqual(bounds, original);
    const anchor = { x: 740, y: 150 };
    const before = worldAt(fit, anchor);
    const zoomed = zoomCameraAt(fit, 2, viewport, anchor);
    const after = worldAt(zoomed, anchor);
    close(after.x, before.x);
    close(after.y, before.y);
    const dragged = gestureCamera(
        fit,
        [{ x: 200, y: 100 }],
        [{ x: 290, y: 145 }],
        viewport,
    );
    close(dragged.x, fit.x - 90 / fit.zoom);
    close(dragged.y, fit.y - 45 / fit.zoom);
    close(dragged.zoom, fit.zoom);
});

test("overview handles vertical spans, empty bounds, and interaction zoom limits", () => {
    close(
        fitBoundsCamera({ minX: 10, maxX: 10, minY: 0, maxY: 6200 }).zoom,
        0.09,
    );
    assert.deepEqual(
        fitBoundsCamera({ minX: 0, maxX: 0, minY: 0, maxY: 0 }),
        DEFAULT_CAMERA,
    );
    assert.deepEqual(
        fitBoundsCamera({ minX: 10, maxX: -10, minY: 0, maxY: 2 }),
        DEFAULT_CAMERA,
    );
    assert.deepEqual(
        fitBoundsCamera({ minX: NaN, maxX: 10, minY: 0, maxY: 2 }),
        DEFAULT_CAMERA,
    );
    assert.equal(
        fitBoundsCamera({ minX: 0, maxX: 1000000, minY: 0, maxY: 620000 }).zoom,
        0.01,
    );
    assert.equal(
        fitBoundsCamera({ minX: 0, maxX: 1, minY: 0, maxY: 1 }).zoom,
        8,
    );
});

test("step zoom keeps its level while the map fills 60% to all of the frame", () => {
    const level = stepZoom(0.3, null);
    assert.equal(level, 1.25 ** -6, "the largest level that shows everything");
    assert.ok(level <= 0.3);
    assert.equal(stepZoom(0.4, level), level, "a quieter day keeps the level");
    assert.equal(stepZoom(0.43, level), level);
    assert.equal(
        stepZoom(0.45, level),
        1.25 ** -4,
        "a much quieter day zooms in",
    );
    assert.equal(
        stepZoom(0.25, level),
        1.25 ** -7,
        "an overflowing day zooms out",
    );
    assert.equal(stepZoom(0.3, null, 1.5, 0.5), 1.5 ** -3);
    assert.equal(stepZoom(Number.NaN, level), level);
    assert.equal(stepZoom(0, null), 1);
});

test("a container-shaped frame removes letterboxing from pan, zoom and fit", () => {
    const wide = { width: 1200, height: 600 };
    const frame = frameFor(wide);
    close(frame.width, 1000);
    close(frame.height, 500);
    const moved = gestureCamera(
        DEFAULT_CAMERA,
        [{ x: 100, y: 100 }],
        [{ x: 220, y: 160 }],
        wide,
        frame,
    );
    close(moved.x, -100);
    close(moved.y, -50);
    const fit = fitBoundsCamera(
        { minX: -1000, maxX: 1000, minY: -250, maxY: 250 },
        frame,
        1,
    );
    close(fit.zoom, 0.5);
    assert.deepEqual(frameFor({ width: 0, height: 10 }), {
        width: 1000,
        height: 620,
    });
});
