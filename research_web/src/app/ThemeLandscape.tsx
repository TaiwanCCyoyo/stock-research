import { useEffect, useId, useState } from "react";
import type { ThemeId } from "./themes";
import "./landscapes.css";

/** Original woodblock-inspired contours; the foam follows the curling crest. */
function Wave({ id }: { id: string }) {
    return (
        <svg viewBox="0 0 600 420" focusable="false">
            <defs>
                <path
                    id={`${id}-finger`}
                    d="M0 0 C8 -18 18 -24 23 -14 C15 -17 13 -8 16 -4 C24 -18 33 -17 34 -6 C25 -10 25 0 28 4 L8 14Z"
                />
            </defs>
            <path
                className="wave-far"
                d="M-20 328 Q80 195 180 287 Q270 342 360 255 Q430 180 500 285 Q550 330 630 282 L630 440H-20Z"
            />
            <path
                className="wave-mid"
                d="M-20 360 C35 330 58 277 82 206 C109 121 153 68 227 73 C297 78 342 137 318 186 C302 213 268 223 243 204 C286 209 299 177 274 153 C242 118 202 151 198 204 C195 286 319 345 405 302 C477 264 538 287 620 334 L620 440H-20Z"
            />
            <path
                className="wave-deep"
                d="M-20 390 C73 327 81 185 144 129 C190 83 250 94 280 125 C223 103 178 131 167 183 C146 265 187 338 282 369 C390 401 432 318 487 320 C554 324 570 379 620 374 L620 440H-20Z"
            />
            <path
                className="wave-foam"
                d="M102 201 C117 125 164 67 227 73 C298 77 345 139 318 186 C305 211 271 221 243 204 C279 203 293 181 278 160 C295 166 306 153 296 141 C284 132 280 154 270 150 C285 135 269 122 258 125 C249 124 253 142 243 139 C249 123 234 115 224 125 C217 129 227 141 218 146 C211 125 194 134 194 148 C184 144 180 151 181 169 C168 153 158 167 161 182 C143 174 133 199 132 213Z"
            />
            <g className="wave-fingers">
                <use
                    href={`#${id}-finger`}
                    transform="translate(117 177) rotate(-38)"
                />
                <use
                    href={`#${id}-finger`}
                    transform="translate(136 136) rotate(-25)"
                />
                <use
                    href={`#${id}-finger`}
                    transform="translate(168 104) rotate(-12)"
                />
                <use
                    href={`#${id}-finger`}
                    transform="translate(209 91) rotate(15)"
                />
                <use
                    href={`#${id}-finger`}
                    transform="translate(254 100) rotate(40)"
                />
                <use
                    href={`#${id}-finger`}
                    transform="translate(290 129) rotate(65)"
                />
            </g>
            <g className="wave-engraving" fill="none" strokeLinecap="round">
                <path d="M7 387 C83 315 81 193 152 129 M25 405 C103 325 100 210 158 151 M62 410 C122 340 120 250 151 199 M98 420 C153 363 142 315 157 270 M153 416 C192 402 225 405 262 419" />
                <path d="M174 178 C163 247 194 298 251 325 M187 185 C182 249 214 285 259 309 M209 225 C231 266 259 280 291 287 M282 342 Q366 380 426 332 Q484 282 536 342 M308 355 Q371 377 424 350 Q485 306 541 361 M386 403 Q448 338 482 354 Q523 363 545 407 M410 414 Q450 368 479 374 Q504 377 520 414" />
            </g>
            <g className="wave-spray">
                {Array.from({ length: 22 }, (_, i) => (
                    <ellipse
                        key={i}
                        cx={92 + ((i * 41) % 253)}
                        cy={40 + ((i * 29) % 100)}
                        rx={1.4 + (i % 3)}
                        ry={2.2 + (i % 3)}
                        transform={`rotate(${i * 17} ${92 + ((i * 41) % 253)} ${40 + ((i * 29) % 100)})`}
                    />
                ))}
            </g>
        </svg>
    );
}

/** Deterministic star fields: dense along the galactic plane, sparse elsewhere. */
const STARS = Array.from({ length: 200 }, (_, i) => {
    const unit = (n: number) => {
        const x = Math.sin(n * 127.1 + 311.7) * 43758.5453;
        return x - Math.floor(x);
    };
    const x = unit(i + 1) * 1440;
    const inBand = i < 130;
    return {
        x,
        y: inBand
            ? 720 - x * 0.58 + (unit(i + 501) - 0.5) * 190
            : unit(i + 501) * 1000,
        r: 0.5 + unit(i + 900) * (i % 17 === 0 ? 2 : 0.9),
        opacity: 0.25 + unit(i + 1200) * 0.65,
    };
});

function Galaxy({ id }: { id: string }) {
    return (
        <svg
            className="galaxy-scene"
            viewBox="0 0 1440 1000"
            preserveAspectRatio="xMaxYMin slice"
            focusable="false"
        >
            <defs>
                <filter
                    id={`${id}-cloud-grain`}
                    x="-10%"
                    y="-20%"
                    width="120%"
                    height="140%"
                >
                    <feTurbulence
                        type="fractalNoise"
                        baseFrequency=".012 .035"
                        numOctaves="3"
                        seed="23"
                        result="noise"
                    />
                    <feColorMatrix
                        in="noise"
                        type="matrix"
                        values="0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 1.5 0 0 0 -.2"
                        result="grain"
                    />
                    <feComposite in="SourceGraphic" in2="grain" operator="in" />
                </filter>
                <filter id={`${id}-dust-soft`}>
                    <feGaussianBlur stdDeviation="8" />
                </filter>
                <radialGradient id={`${id}-halo`}>
                    <stop stopColor="#e5c6ec" stopOpacity=".65" />
                    <stop offset=".25" stopColor="#a595e1" stopOpacity=".38" />
                    <stop offset=".6" stopColor="#657bd6" stopOpacity=".22" />
                    <stop offset="1" stopColor="#4e438a" stopOpacity="0" />
                </radialGradient>
                <radialGradient id={`${id}-core`}>
                    <stop stopColor="#ffedd1" stopOpacity=".85" />
                    <stop offset=".2" stopColor="#ebc7d8" stopOpacity=".5" />
                    <stop offset=".52" stopColor="#b587c5" stopOpacity=".2" />
                    <stop offset="1" stopColor="#ad7dc1" stopOpacity="0" />
                </radialGradient>
            </defs>
            <g transform="translate(0 -200)">
                <g className="galaxy-clouds" transform="rotate(-30 720 500)">
                    <g filter={`url(#${id}-cloud-grain)`}>
                        <ellipse
                            cx="720"
                            cy="500"
                            rx="1120"
                            ry="160"
                            fill={`url(#${id}-halo)`}
                        />
                        <ellipse
                            cx="1120"
                            cy="500"
                            rx="490"
                            ry="110"
                            fill={`url(#${id}-core)`}
                        />
                        <ellipse
                            cx="280"
                            cy="495"
                            rx="390"
                            ry="85"
                            fill={`url(#${id}-halo)`}
                        />
                    </g>
                    <g filter={`url(#${id}-dust-soft)`}>
                        <path
                            className="galaxy-dust"
                            d="M-200 502 Q140 459 330 500 T680 478 Q790 442 880 479 T1160 490 Q1340 440 1640 479 Q1370 476 1210 516 T884 504 Q750 483 630 523 T300 520 Q20 493 -200 526Z"
                        />
                        <path
                            className="galaxy-dust secondary"
                            d="M120 541 Q370 503 550 544 T980 537 Q1160 498 1420 530 Q1230 521 1010 555 T550 565 Q340 536 120 555Z"
                        />
                    </g>
                </g>
            </g>
            <g className="galaxy-stars">
                {STARS.map((star, i) => (
                    <circle
                        key={i}
                        cx={star.x}
                        cy={star.y}
                        r={star.r}
                        opacity={star.opacity}
                    />
                ))}
            </g>
            <g className="galaxy-beacons" fill="none" strokeWidth=".8">
                <path d="M1230 151v16m-8-8h16 M164 781v12m-6-6h12 M1372 409v10m-5-5h10" />
            </g>
        </svg>
    );
}

export function ThemeLandscape({ theme }: { theme: ThemeId }) {
    const id = `landscape-${useId().replace(/:/g, "")}`;
    const [hidden, setHidden] = useState(() => document.hidden);
    useEffect(() => {
        const update = () => setHidden(document.hidden);
        document.addEventListener("visibilitychange", update);
        return () => document.removeEventListener("visibilitychange", update);
    }, []);
    if (theme === "ink" || theme === "sakura") return null;
    return (
        <div
            className={`theme-landscape landscape-${theme}`}
            data-paused={hidden || undefined}
        >
            {theme === "ocean" && (
                <>
                    <div className="wave-print wave-print-near">
                        <Wave id={`${id}-near`} />
                    </div>
                    <div className="wave-print wave-print-far">
                        <Wave id={`${id}-far`} />
                    </div>
                    <div className="ocean-horizon" />
                </>
            )}
            {theme === "plum" && (
                <>
                    <Galaxy id={id} />
                    <div className="galaxy-shimmer" />
                </>
            )}
            {theme === "sunset" && (
                <>
                    <div className="sunset-disc" />
                    <div className="sunset-rays" />
                    <div className="sunset-haze" />
                </>
            )}
            {theme === "forest" && (
                <>
                    <div className="forest-canopy" />
                    <div className="forest-mist" />
                    <div className="forest-light" />
                </>
            )}
            {theme === "sand" && (
                <svg
                    className="sand-dunes"
                    viewBox="0 0 1440 900"
                    preserveAspectRatio="none"
                    focusable="false"
                >
                    <path d="M0 650 Q230 390 660 670 T1440 560V900H0Z" />
                    <path d="M0 740 Q450 420 890 700 T1440 660V900H0Z" />
                    <path d="M0 825 Q460 565 770 785 T1440 730V900H0Z" />
                    <g fill="none">
                        <path d="M0 772 Q450 452 890 732 T1440 692 M0 785 Q450 465 890 745 T1440 705 M0 798 Q450 478 890 758 T1440 718" />
                    </g>
                </svg>
            )}
            {theme === "soda" && (
                <>
                    <div className="soda-glass" />
                    <div className="soda-glint" />
                </>
            )}
        </div>
    );
}
