// @ts-expect-error Node type declarations are intentionally omitted.
import { readFileSync } from "node:fs";

import { JsonFileCatalog } from "../adapters/catalog/json-file.js";
import { MemoryCatalog } from "../adapters/catalog/memory.js";
import { SystemClock } from "../adapters/clock/system.js";
import { TerminalPresenter } from "../adapters/presenter/terminal.js";
import type { Order } from "../core/model.js";
import { PriceOrder } from "../core/price-order.js";

interface LineInput {
  sku: string;
  quantity: number;
}

interface OrderInput {
  customer_tier: string;
  country: string;
  lines: LineInput[];
}

interface Arguments {
  order?: string;
  catalog?: string;
  help: boolean;
}

declare const process: {
  argv: string[];
  env: Record<string, string | undefined>;
  exitCode?: number;
};

function usage(): void {
  console.log("usage: price --order <path> [--catalog <path>]");
  console.log("options: --order, --catalog, --help");
}

function parseArgs(argv: string[]): Arguments {
  const result: Arguments = { help: false };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--help" || arg === "-h") {
      result.help = true;
    } else if (arg === "--order") {
      result.order = argv[++index];
    } else if (arg === "--catalog") {
      result.catalog = argv[++index];
    } else {
      throw new Error(`unknown option: ${arg}`);
    }
  }
  return result;
}

function readOrder(path: string): Order {
  const data = JSON.parse(readFileSync(path, "utf8")) as OrderInput;
  return {
    lines: data.lines.map((line) => ({
      sku: line.sku,
      quantity: line.quantity,
    })),
    customerTier: data.customer_tier,
    country: data.country,
  };
}

function main(): void {
  let args: Arguments;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    usage();
    process.exitCode = 2;
    return;
  }

  if (args.help) {
    usage();
    return;
  }
  if (!args.order) {
    usage();
    process.exitCode = 2;
    return;
  }

  try {
    const catalogPath = args.catalog ?? process.env.PRICING_CATALOG;
    const catalog = catalogPath
      ? new JsonFileCatalog(catalogPath)
      : new MemoryCatalog();
    const result = new PriceOrder(catalog, new SystemClock()).price(
      readOrder(args.order),
    );
    new TerminalPresenter().present(result);
  } catch (error) {
    console.error(
      `error: ${error instanceof Error ? error.message : String(error)}`,
    );
    process.exitCode = 2;
  }
}

main();
