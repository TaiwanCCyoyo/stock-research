import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { gunzipSync } from "node:zlib";
import {
    buildMarketView,
    comparePortfolio,
    POSITIVE_MOVE_SHARE_LABEL,
    POSITIVE_MOVE_SHARE_VERSION,
    validateBundle,
} from "../src/domain/opportunities/model.ts";

function parseArguments(args: string[]) {
    let input: string | undefined;
    let observation: string | undefined;
    let output: string | undefined;
    const portfolioIds: string[] = [];
    for (let i = 0; i < args.length; i++) {
        const flag = args[i];
        if (!["--input", "--date", "--portfolio", "--output"].includes(flag))
            throw new Error(`Unknown argument: ${flag}`);
        const value = args[++i];
        if (!value || value.startsWith("--"))
            throw new Error(`Missing value for ${flag}`);
        if (flag === "--portfolio") {
            const ids = value
                .split(",")
                .map((id) => id.trim())
                .filter(Boolean);
            if (ids.length === 0)
                throw new Error(
                    "--portfolio requires at least one portfolio id",
                );
            portfolioIds.push(...ids);
        }
        if (flag === "--input") {
            if (input) throw new Error("Repeated --input");
            input = value;
        }
        if (flag === "--date") {
            if (observation) throw new Error("Repeated --date");
            observation = value;
        }
        if (flag === "--output") {
            if (output) throw new Error("Repeated --output");
            output = value;
        }
    }
    if (!input || !observation)
        throw new Error(
            "Usage: node --experimental-strip-types scripts/compare-opportunities.mts --input bundle.json --date YYYY-MM-DD [--portfolio id,id] [--output new-file.json]",
        );
    return {
        input: resolve(input),
        date: observation,
        output: output && resolve(output),
        portfolioIds: [...new Set(portfolioIds)],
    };
}

async function main() {
    const args = parseArguments(process.argv.slice(2));
    const stored = await readFile(args.input);
    const bytes = args.input.toLowerCase().endsWith(".gz")
        ? gunzipSync(stored, { maxOutputLength: 64 * 1024 * 1024 })
        : stored;
    const bundle = validateBundle(
        JSON.parse(bytes.toString("utf8").replace(/^\uFEFF/, "")),
    );
    const view = buildMarketView(bundle, args.date);
    for (const id of args.portfolioIds)
        if (!bundle.portfolios.some((portfolio) => portfolio.id === id))
            throw new Error(`Unknown portfolio: ${id}`);
    const portfolios =
        args.portfolioIds.length > 0
            ? bundle.portfolios.filter((portfolio) =>
                  args.portfolioIds.includes(portfolio.id),
              )
            : bundle.portfolios;
    const result = {
        schema: "opportunity-comparison.v1",
        bundle: {
            schema: bundle.schema,
            id: bundle.id,
            label: bundle.label,
            kind: bundle.kind,
            asOf: bundle.asOf,
            priceBasis: bundle.priceBasis,
            catalogCoverage: bundle.catalogCoverage,
            ruleVersion: bundle.ruleVersion,
            selectionPolicy: bundle.selectionPolicy,
            classificationVersion: bundle.classificationVersion,
            sources: bundle.sources,
            limitations: bundle.limitations,
        },
        input: args.input,
        positiveMoveShareVersion: POSITIVE_MOVE_SHARE_VERSION,
        positiveMoveShareLabel: POSITIVE_MOVE_SHARE_LABEL,
        market: view,
        comparisons: portfolios.map((portfolio) =>
            comparePortfolio(bundle, view, portfolio),
        ),
    };
    const json = `${JSON.stringify(result, null, 2)}\n`;
    if (args.output)
        await writeFile(args.output, json, { encoding: "utf8", flag: "wx" });
    else process.stdout.write(json);
}

main().catch((error: unknown) => {
    process.stderr.write(
        `${error instanceof Error ? error.message : String(error)}\n`,
    );
    process.exitCode = 1;
});
