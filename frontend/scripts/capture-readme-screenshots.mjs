import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const playwrightCli = fileURLToPath(
  new URL("../node_modules/@playwright/test/cli.js", import.meta.url),
);

const child = spawn(
  process.execPath,
  [playwrightCli, "test", "tests/e2e/site-ledger.spec.ts", "--grep", "README product screenshots"],
  {
    cwd: fileURLToPath(new URL("..", import.meta.url)),
    env: { ...process.env, README_SCREENSHOT_REVIEW: "1" },
    stdio: "inherit",
  },
);

child.on("error", (error) => {
  console.error(error);
  process.exitCode = 1;
});

child.on("exit", (code, signal) => {
  if (signal) {
    console.error(`Screenshot capture stopped by ${signal}.`);
    process.exitCode = 1;
    return;
  }
  process.exitCode = code ?? 1;
});
