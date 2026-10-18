// Frontend + mock API together, for UI work with no backend and no model calls:
//   npm run dev:mock    -> http://localhost:3000  (sign in: admin@mock.test / "mock passphrase 1")
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const port = process.env.MOCK_PORT ?? "8100";
const env = { ...process.env, MOCK_PORT: port, API_URL: `http://127.0.0.1:${port}` };
delete env.ORDERINTEL_LOCAL;

const mock = spawn(process.execPath, [path.join(here, "mock-api.mjs")], { stdio: "inherit", env });
const next = spawn(process.execPath, [require.resolve("next/dist/bin/next"), "dev", ...process.argv.slice(2)], {
  stdio: "inherit",
  env,
});
const stop = () => {
  mock.kill();
  next.kill();
};
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
next.on("exit", (code) => {
  mock.kill();
  process.exit(code ?? 0);
});
