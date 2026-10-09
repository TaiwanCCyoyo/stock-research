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

/** Explicit overview action; fitting changes the camera, never world geometry. */
export function fitBoundsCamera(bounds: {
    minX: number;
    minY: number;
    maxX: number;
    maxY: number;
}): Camera {
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
                Math.min(WORLD_WIDTH / width, WORLD_HEIGHT / height) * 0.9,
            ),
        ),
    };
}

export interface OverviewState {
    camera: Camera;
    initialized: boolean;
}

/** Empty/zero-area dates do not consume the one initial overview. Later dates never refit. */
export function initialOverview(
    state: OverviewState,
    bounds: Parameters<typeof fitBoundsCamera>[0],
    hasPositiveArea: boolean,
): OverviewState {
    if (state.initialized || !hasPositiveArea) return state;
    return { camera: fitBoundsCamera(bounds), initialized: true };
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
): Camera {
    // SVG uses xMidYMid meet; narrow/mobile viewports can include letterboxing.
    const scale = Math.min(
        viewport.width / WORLD_WIDTH,
        viewport.height / WORLD_HEIGHT,
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
): Camera {
    return transformCamera(camera, anchor, anchor, factor, viewport);
}

/** One pointer pans; two pointers preserve the world point under their midpoint. */
export function gestureCamera(
    camera: Camera,
    previous: readonly ScreenPoint[],
    current: readonly ScreenPoint[],
    viewport: Viewport,
): Camera {
    const count = Math.min(2, previous.length, current.length);
    if (!count) return camera;
    if (count === 1)
        return transformCamera(camera, previous[0], current[0], 1, viewport);
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
