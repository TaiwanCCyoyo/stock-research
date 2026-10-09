export interface Camera {
    x: number;
    y: number;
    zoom: number;
}
export interface ScreenPoint {
    x: number;
    y: number;
}
export interface Viewport {
    width: number;
    height: number;
}

export const DEFAULT_CAMERA: Readonly<Camera> = { x: 0, y: 0, zoom: 1 };
export const WORLD_WIDTH = 1000;
export const WORLD_HEIGHT = 620;
const MIN_ZOOM = 0.01;
const MAX_ZOOM = 8;
/** World-unit size of what the SVG shows at zoom 1. */
export interface WorldFrame {
    width: number;
    height: number;
}
export const WORLD_FRAME: Readonly<WorldFrame> = {
    width: WORLD_WIDTH,
    height: WORLD_HEIGHT,
};

/** A frame with the container's own proportions, so the SVG never letterboxes. */
export function frameFor(viewport: Viewport): WorldFrame {
    return viewport.width > 0 && viewport.height > 0
        ? {
              width: WORLD_WIDTH,
              height: (WORLD_WIDTH * viewport.height) / viewport.width,
          }
        : { ...WORLD_FRAME };
}

/** Explicit overview action; fitting changes the camera, never world geometry. */
export function fitBoundsCamera(
    bounds: {
        minX: number;
        minY: number;
        maxX: number;
        maxY: number;
    },
    frame: WorldFrame = WORLD_FRAME,
    fill = 0.9,
): Camera {
    const width = bounds.maxX - bounds.minX;
    const height = bounds.maxY - bounds.minY;
    if (
        !Object.values(bounds).every(Number.isFinite) ||
        width < 0 ||
        height < 0 ||
        (width === 0 && height === 0)
    )
        return { ...DEFAULT_CAMERA };
    return {
        x: bounds.minX + width / 2,
        y: bounds.minY + height / 2,
        zoom: Math.max(
            MIN_ZOOM,
            Math.min(
                MAX_ZOOM,
                Math.min(frame.width / width, frame.height / height) * fill,
            ),
        ),
    };
}

/**
 * Step zoom: levels are powers of `ratio`. Keep the current level while the
 * map fills between `minFill` and all of the frame; otherwise jump to the
 * largest level that still shows everything. Quiet days zoom in, busy days
 * zoom out, and small daily changes never move the camera.
 */
export function stepZoom(
    fitZoom: number,
    currentZoom: number | null,
    ratio = 1.25,
    minFill = 0.6,
): number {
    if (!Number.isFinite(fitZoom) || fitZoom <= 0)
        return currentZoom ?? DEFAULT_CAMERA.zoom;
    const tolerance = 1 + 1e-9;
    if (
        currentZoom !== null &&
        currentZoom <= fitZoom * tolerance &&
        currentZoom * tolerance >= fitZoom * minFill
    )
        return currentZoom;
    const level = Math.floor(Math.log(fitZoom) / Math.log(ratio) + 1e-9);
    return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, ratio ** level));
}

export function isDefaultCamera(
    camera: Camera,
    reference: Camera = DEFAULT_CAMERA,
): boolean {
    return (
        Math.abs(camera.x - reference.x) < 1e-6 &&
        Math.abs(camera.y - reference.y) < 1e-6 &&
        Math.abs(camera.zoom - reference.zoom) < 1e-6
    );
}

function transformCamera(
    camera: Camera,
    before: ScreenPoint,
    after: ScreenPoint,
    factor: number,
    viewport: Viewport,
    frame: WorldFrame,
): Camera {
    // SVG uses xMidYMid meet; a frame that differs from the viewport letterboxes.
    const scale = Math.min(
        viewport.width / frame.width,
        viewport.height / frame.height,
    );
    if (
        !Number.isFinite(scale) ||
        scale <= 0 ||
        !Number.isFinite(factor) ||
        factor <= 0
    )
        return camera;
    const zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, camera.zoom * factor));
    const center = { x: viewport.width / 2, y: viewport.height / 2 };
    return {
        x:
            camera.x +
            (before.x - center.x) / (scale * camera.zoom) -
            (after.x - center.x) / (scale * zoom),
        y:
            camera.y +
            (before.y - center.y) / (scale * camera.zoom) -
            (after.y - center.y) / (scale * zoom),
        zoom,
    };
}

export function zoomCameraAt(
    camera: Camera,
    factor: number,
    viewport: Viewport,
    anchor: ScreenPoint = { x: viewport.width / 2, y: viewport.height / 2 },
    frame: WorldFrame = WORLD_FRAME,
): Camera {
    return transformCamera(camera, anchor, anchor, factor, viewport, frame);
}

/** One pointer pans; two pointers preserve the world point under their midpoint. */
export function gestureCamera(
    camera: Camera,
    previous: readonly ScreenPoint[],
    current: readonly ScreenPoint[],
    viewport: Viewport,
    frame: WorldFrame = WORLD_FRAME,
): Camera {
    const count = Math.min(2, previous.length, current.length);
    if (!count) return camera;
    if (count === 1)
        return transformCamera(
            camera,
            previous[0],
            current[0],
            1,
            viewport,
            frame,
        );
    const midpoint = (points: readonly ScreenPoint[]) => ({
        x: (points[0].x + points[1].x) / 2,
        y: (points[0].y + points[1].y) / 2,
    });
    const distance = (points: readonly ScreenPoint[]) =>
        Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y);
    const beforeDistance = distance(previous);
    const afterDistance = distance(current);
    const factor =
        beforeDistance > 0 && afterDistance > 0
            ? afterDistance / beforeDistance
            : 1;
    return transformCamera(
        camera,
        midpoint(previous),
        midpoint(current),
        factor,
        viewport,
        frame,
    );
}

/** Regular wheel scrolling is left to the page; modified wheel includes trackpad pinch. */
export function wheelZoomFactor(
    event: {
        ctrlKey: boolean;
        metaKey: boolean;
        deltaY: number;
        deltaMode: number;
    },
    viewportHeight: number,
): number | null {
    if (
        (!event.ctrlKey && !event.metaKey) ||
        !Number.isFinite(event.deltaY) ||
        event.deltaY === 0
    )
        return null;
    const unit =
        event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewportHeight : 1;
    return Math.exp(
        -Math.max(-500, Math.min(500, event.deltaY * unit)) * 0.003,
    );
}
