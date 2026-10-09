import { createHash } from "node:crypto";
import { open, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const CASES = [
    ["3017", "2019-01-02", "2026-08-14", "長期路徑"],
    ["2330", "2019-01-02", "2026-08-14", "長期路徑"],
    ["2609", "2020-01-02", "2022-12-30", "航運週期"],
    ["9919", "2019-01-02", "2021-12-30", "急遽移動"],
    ["3481", "2019-01-02", "2023-12-29", "循環或盤整"],
    ["2002", "2019-01-02", "2023-12-29", "循環或盤整"],
    ["2498", "2021-01-04", "2023-12-29", "反彈與退回"],
    ["4743", "2019-01-02", "2022-12-30", "波動路徑"],
];

const LIMITATIONS = [
    "此案例的分類是市場圖譜所記錄的回溯分類，不是歷史時點成分主張。",
    "本投影未包含成交量，不能判定零量或停牌狀態。",
    "本投影未提供逐日公司行動事件；調整價格定義以市場圖譜 provenance 為準。",
    "此預覽僅涵蓋釘選的 2019-01-02..2026-08-14 投影，並非完整 2010 年起歷史。",
    "缺失報價維持 null，沒有內插或以前值填補。",
];

function sha256(bytes) {
    return createHash("sha256").update(bytes).digest("hex");
}

function fail(message) {
    throw new Error(`Invalid market-atlas.v1: ${message}`);
}

function isPrice(value) {
    return (
        value === null ||
        (typeof value === "number" && Number.isFinite(value) && value > 0)
    );
}

function isCalendarDate(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value))
        return false;
    const time = Date.parse(`${value}T00:00:00Z`);
    return (
        Number.isFinite(time) &&
        new Date(time).toISOString().slice(0, 10) === value
    );
}

function validateAtlas(atlas) {
    if (
        !atlas ||
        atlas.schema !== "market-atlas.v1" ||
        !Array.isArray(atlas.dates) ||
        !Array.isArray(atlas.stocks)
    )
        fail("schema, dates, and stocks are required");
    if (typeof atlas.catalogHash !== "string" || !atlas.catalogHash.trim())
        fail("catalogHash is required");
    if (
        !Array.isArray(atlas.limitations) ||
        !Array.from(atlas.limitations).every(
            (value) => typeof value === "string",
        )
    )
        fail("limitations must be a string array");
    const seenDates = new Set();
    atlas.dates.forEach((date, index) => {
        if (!isCalendarDate(date)) fail(`date ${index} is invalid`);
        if (
            seenDates.has(date) ||
            (index > 0 && atlas.dates[index - 1] >= date)
        )
            fail("dates must be unique and increasing");
        seenDates.add(date);
    });
    const seenCodes = new Set();
    atlas.stocks.forEach((stock) => {
        if (!stock || typeof stock.code !== "string" || !stock.code)
            fail("stock code is invalid");
        if (seenCodes.has(stock.code))
            fail(`duplicate stock code ${stock.code}`);
        seenCodes.add(stock.code);
        for (const key of ["raw", "adjusted"]) {
            if (
                !Array.isArray(stock[key]) ||
                stock[key].length !== atlas.dates.length
            )
                fail(`${stock.code}.${key} is not aligned to dates`);
            if (!stock[key].every(isPrice))
                fail(`${stock.code}.${key} has an invalid price`);
        }
        if (
            !Array.isArray(stock.quality) ||
            !stock.quality.every((value) => typeof value === "string")
        )
            fail(`${stock.code}.quality is invalid`);
        if (
            stock.qualityFindings !== undefined &&
            (!Array.isArray(stock.qualityFindings) ||
                !stock.qualityFindings.every(
                    (finding) =>
                        finding &&
                        isCalendarDate(finding.date) &&
                        typeof finding.kind === "string" &&
                        finding.kind.trim().length > 0,
                ))
        )
            fail(`${stock.code}.qualityFindings is invalid`);
    });
}

function flagsFor(stock, date) {
    const flags = stock.quality.map((kind) => `stock-quality:${kind}`);
    for (const finding of stock.qualityFindings ?? []) {
        if (finding.date === date) flags.push(`dated-quality:${finding.kind}`);
    }
    return flags;
}

function priceBasis(atlas) {
    const provenance =
        atlas.provenance && typeof atlas.provenance === "object"
            ? atlas.provenance
            : {};
    const raw =
        typeof provenance.rawDefinition === "string"
            ? provenance.rawDefinition
            : "market-atlas.v1 raw close";
    const adjusted =
        typeof provenance.splitAdjustedDefinition === "string"
            ? provenance.splitAdjustedDefinition
            : "market-atlas.v1 adjusted close";
    return `raw: ${raw}; adjusted: ${adjusted}`;
}

export function buildCases(atlas, inputHash) {
    validateAtlas(atlas);
    if (typeof inputHash !== "string" || !/^[a-f0-9]{64}$/.test(inputHash))
        throw new Error("inputHash must be a SHA-256 hex digest");
    const stocks = new Map(atlas.stocks.map((stock) => [stock.code, stock]));
    const cases = CASES.map(([code, requestedFrom, requestedTo, category]) => {
        const stock = stocks.get(code);
        if (!stock) fail(`required case code ${code} is missing`);
        const points = atlas.dates.flatMap((date, index) =>
            date >= requestedFrom && date <= requestedTo
                ? [
                      {
                          date,
                          raw: stock.raw[index],
                          adjusted: stock.adjusted[index],
                          flags: flagsFor(stock, date),
                      },
                  ]
                : [],
        );
        if (!points.length)
            fail(
                `required case ${code} has no rows in ${requestedFrom}..${requestedTo}`,
            );
        return {
            id: `historical-${code}-${requestedFrom}-${requestedTo}`,
            name:
                typeof stock.name === "string" && stock.name.trim()
                    ? stock.name
                    : `代碼 ${code}`,
            code,
            kind: "historical",
            category,
            question: `回溯檢視：此預先選定的 ${category} 路徑如何呈現分段、啟動與回撤？`,
            points,
            source: {
                label: `market-atlas.v1 回溯檢視；實際日期涵蓋 ${points[0].date}..${points.at(-1).date}`,
                from: points[0].date,
                to: points.at(-1).date,
                priceBasis: priceBasis(atlas),
                hash: inputHash,
                catalogHash: atlas.catalogHash,
                limitations: [...LIMITATIONS, ...atlas.limitations],
            },
        };
    });
    return {
        schema: "wave-lab-cases.v1",
        projectionHash: inputHash,
        catalogHash: atlas.catalogHash,
        cases,
    };
}

export async function exportCases(input, output) {
    const inputPath = path.resolve(input);
    const outputPath = path.resolve(output);
    if (inputPath === outputPath)
        throw new Error("output cannot overwrite input");
    const inputBytes = await readFile(inputPath);
    const inputHash = sha256(inputBytes);
    let atlas;
    try {
        atlas = JSON.parse(inputBytes.toString("utf8"));
    } catch (error) {
        throw new Error(`Invalid market-atlas.v1 JSON: ${error.message}`);
    }
    const bundle = buildCases(atlas, inputHash);
    if (sha256(inputBytes) !== inputHash)
        throw new Error("input buffer hash changed unexpectedly");
    const handle = await open(outputPath, "wx");
    try {
        await handle.writeFile(JSON.stringify(bundle));
    } finally {
        await handle.close();
    }
    return bundle;
}

export async function main(argv = process.argv.slice(2)) {
    const options = new Map();
    for (let index = 0; index < argv.length; index += 2) {
        if (!argv[index]?.startsWith("--") || argv[index + 1] === undefined)
            throw new Error(
                "usage: --input <market-atlas.json> --output <wave-lab-cases.json>",
            );
        options.set(argv[index], argv[index + 1]);
    }
    if (
        options.size !== 2 ||
        !options.has("--input") ||
        !options.has("--output")
    )
        throw new Error(
            "usage: --input <market-atlas.json> --output <wave-lab-cases.json>",
        );
    return exportCases(options.get("--input"), options.get("--output"));
}

if (
    process.argv[1] &&
    path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
    main()
        .then((bundle) =>
            process.stdout.write(
                `${JSON.stringify({ schema: bundle.schema, cases: bundle.cases.length })}\n`,
            ),
        )
        .catch((error) => {
            process.stderr.write(`${error.message}\n`);
            process.exitCode = 1;
        });
}
