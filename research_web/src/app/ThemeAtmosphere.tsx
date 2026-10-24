import { useEffect, useRef } from "react";
import type { ThemeId } from "./themes";
import { ThemeLandscape } from "./ThemeLandscape";
import "./atmosphere.css";

type Context = CanvasRenderingContext2D;
type Mote = {
    x: number;
    y: number;
    depth: number;
    phase: number;
    angle: number;
    variant: number;
};

/** An original curled, notched petal with a translucent edge and central vein. */
function petal(context: Context, tone: number) {
    const gradient = context.createLinearGradient(-10, -18, 12, 16);
    gradient.addColorStop(0, "#fff6fa");
    gradient.addColorStop(0.45, ["#f7b4ce", "#ffd9e5", "#ee97ba"][tone]);
    gradient.addColorStop(1, "#d66698");
    context.fillStyle = gradient;
    context.beginPath();
    context.moveTo(0, 18);
    context.bezierCurveTo(-21, 3, -16, -18, -4, -16);
    context.quadraticCurveTo(-1, -15, 0, -11);
    context.quadraticCurveTo(5, -22, 12, -12);
    context.bezierCurveTo(23, 0, 6, 13, 0, 18);
    context.fill();
    context.strokeStyle = "#fff6fa80";
    context.lineWidth = 0.6;
    context.beginPath();
    context.moveTo(0, 16);
    context.quadraticCurveTo(4, 3, 1, -9);
    context.stroke();
}

function sprites(theme: ThemeId, dark: boolean) {
    return Array.from({ length: 3 }, (_, variant) => {
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = 96;
        const context = canvas.getContext("2d")!;
        context.translate(48, 48);
        if (theme === "sakura") {
            petal(context, variant);
        } else if (theme === "soda" || theme === "ink") {
            const color =
                theme === "ink"
                    ? dark
                        ? "#e8e4db"
                        : "#4c5055"
                    : dark
                      ? "#e0ffb0"
                      : "#6d9d32";
            context.strokeStyle = `${color}70`;
            context.lineWidth = 1;
            context.beginPath();
            context.arc(0, 0, 17, 0, Math.PI * 2);
            if (theme === "soda") {
                const glass = context.createRadialGradient(-6, -7, 1, 0, 0, 18);
                glass.addColorStop(0, "#ffffff45");
                glass.addColorStop(0.3, "#f5ffcf08");
                glass.addColorStop(0.8, "#b2d87108");
                glass.addColorStop(1, "#e8ffc04a");
                context.fillStyle = glass;
                context.fill();
            }
            context.stroke();
            context.strokeStyle = `${color}c0`;
            context.beginPath();
            context.arc(0, 0, 14, Math.PI, Math.PI * 1.45);
            context.stroke();
        } else {
            const color = theme === "forest" ? "#d5efa0" : "#efc78e";
            const glow = context.createRadialGradient(0, 0, 0, 0, 0, 30);
            glow.addColorStop(0, `${color}e0`);
            glow.addColorStop(0.12, `${color}b0`);
            glow.addColorStop(1, `${color}00`);
            context.fillStyle = glow;
            context.fillRect(-32, -32, 64, 64);
        }
        return canvas;
    });
}

/** Static edge scenery is rasterized once per resize, never in the animation loop. */
function scenery(
    context: Context,
    width: number,
    height: number,
    theme: ThemeId,
    dark: boolean,
) {
    let seed = 47;
    const random = () => {
        seed = (seed * 16807) % 2147483647;
        return seed / 2147483647;
    };
    context.clearRect(0, 0, width, height);
    if (theme === "sakura" || theme === "forest") {
        for (const side of [-1, 1]) {
            context.save();
            context.translate(side === -1 ? 0 : width, side === -1 ? 60 : 180);
            context.scale(side === -1 ? 1 : -1, 1);
            const reach = Math.min(width * 0.22, 285);
            context.lineCap = "round";
            context.strokeStyle = dark ? "#97718138" : "#664b6140";
            context.lineWidth = 5;
            context.beginPath();
            context.moveTo(-12, 170);
            context.bezierCurveTo(30, 80, reach * 0.45, 68, reach, 15);
            context.stroke();
            for (let branch = 0; branch < 9; branch++) {
                const x = (reach * branch) / 10;
                const y = 140 - branch * 12;
                context.lineWidth = 1.6;
                context.beginPath();
                context.moveTo(x, y);
                context.quadraticCurveTo(x + 15, y - 32, x + 38, y - 48);
                context.stroke();
                for (let blossom = 0; blossom < 7; blossom++) {
                    const bx = x + 18 + random() * 50;
                    const by = y - 25 - random() * 50;
                    context.save();
                    context.translate(bx, by);
                    if (theme === "sakura") {
                        context.globalAlpha =
                            (dark ? 0.23 : 0.43) + random() * 0.15;
                        const size = 0.14 + random() * 0.12;
                        context.scale(size, size);
                        for (let leaf = 0; leaf < 5; leaf++) {
                            context.rotate((Math.PI * 2) / 5);
                            context.save();
                            context.translate(0, -17);
                            petal(context, blossom % 3);
                            context.restore();
                        }
                    } else {
                        context.rotate(random() * Math.PI);
                        context.fillStyle = dark ? "#739f7926" : "#689b6936";
                        context.beginPath();
                        context.ellipse(0, 0, 5, 17, 0, 0, Math.PI * 2);
                        context.fill();
                    }
                    context.restore();
                }
            }
            context.restore();
        }
    } else if (theme === "ink") {
        for (let i = 0; i < 7; i++) {
            context.beginPath();
            const y = height * 0.65 + i * 24;
            context.moveTo(0, y);
            context.bezierCurveTo(
                width * 0.32,
                y - 150,
                width * 0.58,
                y + 150,
                width,
                y - 70,
            );
            context.strokeStyle = dark ? "#f0ebe312" : "#454d5510";
            context.lineWidth = 12;
            context.stroke();
        }
    }
}

export function ThemeAtmosphere({
    theme,
    dark,
}: {
    theme: ThemeId;
    dark: boolean;
}) {
    const scene = useRef<HTMLCanvasElement>(null);
    const motion = useRef<HTMLCanvasElement>(null);
    useEffect(() => {
        // These scenes use static SVG art and compositor-only motion.
        if (theme === "ocean" || theme === "plum") return;
        const background = scene.current;
        const element = motion.current;
        const context = element?.getContext("2d");
        const still = background?.getContext("2d");
        if (!background || !element || !context || !still) return;
        const reduced = matchMedia("(prefers-reduced-motion: reduce)");
        const atlas = sprites(theme, dark);
        let width = 0,
            height = 0,
            frame = 0,
            last = 0,
            elapsed = 0;
        let motes: Mote[] = [];
        const resize = () => {
            width = innerWidth;
            height = innerHeight;
            const ratio = Math.min(devicePixelRatio || 1, 1.5);
            for (const canvas of [background, element]) {
                canvas.width = Math.round(width * ratio);
                canvas.height = Math.round(height * ratio);
                canvas.getContext("2d")!.setTransform(ratio, 0, 0, ratio, 0, 0);
            }
            scenery(still, width, height, theme, dark);
            const count =
                theme === "ink"
                    ? 5
                    : theme === "soda"
                      ? Math.min(48, Math.round(width / 30) + 14)
                      : Math.min(32, Math.round(width / 45) + 8);
            motes = Array.from({ length: count }, (_, i) => ({
                x: Math.random() * width,
                y: Math.random() * height,
                depth: 0.3 + Math.random() * 0.7,
                phase: Math.random() * Math.PI * 2,
                angle: Math.random() * Math.PI * 2,
                variant: i % 3,
            }));
        };
        const tick = (now: number) => {
            frame = requestAnimationFrame(tick);
            if (now - last < 1000 / 30) return;
            const dt = Math.min((now - last) / 1000, 0.07);
            last = now;
            elapsed += dt;
            context.clearRect(0, 0, width, height);
            for (const mote of motes) {
                const falling = theme === "sakura" || theme === "sand";
                mote.y +=
                    (falling ? 14 : theme === "soda" ? -24 : -5) *
                    mote.depth *
                    dt;
                mote.x +=
                    (Math.sin(elapsed * 0.35 + mote.phase) * 9 +
                        (falling ? 7 : 2)) *
                    mote.depth *
                    dt;
                if (mote.y > height + 40) mote.y = -40;
                if (mote.y < -40) mote.y = height + 40;
                if (mote.x > width + 40) mote.x = -40;
                if (mote.x < -40) mote.x = width + 40;
                context.save();
                context.translate(mote.x, mote.y);
                const flutter = Math.sin(elapsed * 0.8 + mote.phase);
                context.rotate(mote.angle + elapsed * 0.12 * mote.depth);
                if (theme === "sakura")
                    context.scale(1, 0.25 + Math.abs(flutter) * 0.75);
                const size =
                    theme === "sakura"
                        ? 25 + mote.depth * 40
                        : theme === "soda"
                          ? 40 + mote.depth * 95
                          : theme === "ink"
                            ? 70 + mote.depth * 80
                            : 12 + mote.depth * 42;
                // Keep the central reading column calm; near and far particles differ in scale and opacity.
                const edge = Math.abs(mote.x / width - 0.5) > 0.36;
                context.globalAlpha =
                    (edge ? 0.65 : 0.28) *
                    mote.depth *
                    (theme === "forest"
                        ? 0.5 + 0.5 * Math.sin(elapsed + mote.phase) ** 2
                        : 1);
                context.drawImage(
                    atlas[mote.variant],
                    -size / 2,
                    -size / 2,
                    size,
                    size,
                );
                context.restore();
            }
        };
        const start = () => {
            cancelAnimationFrame(frame);
            context.clearRect(0, 0, width, height);
            if (reduced.matches || document.hidden) return;
            last = performance.now();
            frame = requestAnimationFrame(tick);
        };
        resize();
        start();
        const onResize = () => {
            resize();
            start();
        };
        addEventListener("resize", onResize);
        reduced.addEventListener("change", start);
        document.addEventListener("visibilitychange", start);
        return () => {
            cancelAnimationFrame(frame);
            removeEventListener("resize", onResize);
            reduced.removeEventListener("change", start);
            document.removeEventListener("visibilitychange", start);
        };
    }, [theme, dark]);
    return (
        <div className="theme-atmosphere" data-scene={theme} aria-hidden="true">
            <div className="atmosphere-light" />
            <ThemeLandscape theme={theme} />
            {theme !== "ocean" && theme !== "plum" && (
                <>
                    <canvas ref={scene} className="atmosphere-scenery" />
                    <canvas ref={motion} className="atmosphere-motion" />
                </>
            )}
        </div>
    );
}
