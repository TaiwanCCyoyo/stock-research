import { useEffect, useRef } from "react";

interface Petal {
    x: number;
    y: number;
    size: number;
    speed: number;
    sway: number;
    phase: number;
    spin: number;
    angle: number;
    tone: number;
}

const TONES = ["#f9a8c9", "#fbc4d8", "#f48fb5", "#ffd6e4"];

function newPetal(width: number, height: number, anywhere: boolean): Petal {
    return {
        x: Math.random() * width,
        y: anywhere ? Math.random() * height : -20,
        size: 6 + Math.random() * 7,
        speed: 18 + Math.random() * 26,
        sway: 14 + Math.random() * 26,
        phase: Math.random() * Math.PI * 2,
        spin: (Math.random() - 0.5) * 1.6,
        angle: Math.random() * Math.PI * 2,
        tone: Math.floor(Math.random() * TONES.length),
    };
}

/** Decorative falling cherry petals behind the page; never intercepts input. */
export function PetalLayer({ dark }: { dark: boolean }) {
    const canvas = useRef<HTMLCanvasElement>(null);
    useEffect(() => {
        const element = canvas.current;
        const context = element?.getContext("2d");
        if (!element || !context) return;
        const reduced = matchMedia("(prefers-reduced-motion: reduce)");
        let width = 0,
            height = 0,
            frame = 0,
            last = performance.now();
        let petals: Petal[] = [];
        const resize = () => {
            const ratio = Math.min(devicePixelRatio || 1, 2);
            width = innerWidth;
            height = innerHeight;
            element.width = width * ratio;
            element.height = height * ratio;
            context.setTransform(ratio, 0, 0, ratio, 0, 0);
            const count = Math.round(Math.min(34, Math.max(14, width / 40)));
            petals = Array.from({ length: count }, () =>
                newPetal(width, height, true),
            );
        };
        const draw = (petal: Petal) => {
            context.save();
            context.translate(petal.x, petal.y);
            context.rotate(petal.angle);
            context.scale(1, 0.55 + 0.45 * Math.abs(Math.sin(petal.phase)));
            context.fillStyle = TONES[petal.tone]!;
            context.beginPath();
            const s = petal.size;
            context.moveTo(0, -s);
            context.bezierCurveTo(s * 0.9, -s * 0.7, s * 0.7, s * 0.6, 0, s);
            context.bezierCurveTo(-s * 0.7, s * 0.6, -s * 0.9, -s * 0.7, 0, -s);
            context.fill();
            context.restore();
        };
        const tick = (now: number) => {
            const dt = Math.min(0.05, (now - last) / 1000);
            last = now;
            context.clearRect(0, 0, width, height);
            context.globalAlpha = dark ? 0.42 : 0.6;
            for (const petal of petals) {
                petal.phase += dt * 1.4;
                petal.y += petal.speed * dt;
                petal.x += Math.sin(petal.phase) * petal.sway * dt;
                petal.angle += petal.spin * dt;
                if (petal.y > height + 20)
                    Object.assign(petal, newPetal(width, height, false));
                draw(petal);
            }
            frame = requestAnimationFrame(tick);
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
        addEventListener("resize", resize);
        reduced.addEventListener("change", start);
        document.addEventListener("visibilitychange", start);
        return () => {
            cancelAnimationFrame(frame);
            removeEventListener("resize", resize);
            reduced.removeEventListener("change", start);
            document.removeEventListener("visibilitychange", start);
        };
    }, [dark]);
    return <canvas ref={canvas} className="petal-layer" aria-hidden="true" />;
}
