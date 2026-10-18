// Run a Next.js command in local mode (ORDERINTEL_LOCAL=1) on any OS:
//   node scripts/with-local.mjs dev   |   node scripts/with-local.mjs start
// In local mode the server reads ACCESS_CODE from the project's .env itself
// (see src/lib/server/upstream.ts); the browser never receives it.
import { spawn } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const nextBin = require.resolve("next/dist/bin/next");
const child = spawn(process.execPath, [nextBin, ...process.argv.slice(2)], {
  stdio: "inherit",
  env: { ...process.env, ORDERINTEL_LOCAL: "1" },
});
child.on("exit", (code) => process.exit(code ?? 0));
