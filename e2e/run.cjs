// Browser tests for Profit Hunter.
//
//   node e2e/run.cjs            run every test
//   node e2e/run.cjs failure    run tests whose name contains "failure"
//
// Each test starts its OWN backend on a throwaway database and photo folder
// in the system temp directory, using the MOCK AI provider with simulated
// billing. Your real database is never opened and nothing is sent anywhere.
// All sellers, items, listings and images are SYNTHETIC.
//
// Needs: the built web app (cd frontend && npm run build) and Playwright
// (cd e2e && npm install && npx playwright install chromium).
const { chromium } = require("playwright");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const tests = require("./tests.cjs");

const ROOT = path.resolve(__dirname, "..");
const PYTHON = process.env.PH_PYTHON || path.join(ROOT, "backend", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const SHOTS = process.env.PH_E2E_SCREENSHOTS || "";
let port = 8770;

async function startServer() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "profit-hunter-e2e-"));
  const env = { ...process.env, PROFIT_HUNTER_DB: path.join(dir, "test.db"), PROFIT_HUNTER_IMAGES: path.join(dir, "images"), PROFIT_HUNTER_MOCK_BILLING: "1" };
  delete env.OPENAI_API_KEY;
  const p = ++port;
  const log = [];
  const child = spawn(PYTHON, ["-m", "uvicorn", "profit_hunter.api.main:app", "--port", String(p), "--log-level", "warning"], { cwd: path.join(ROOT, "backend"), env });
  child.stderr.on("data", (d) => log.push(String(d)));
  const base = `http://127.0.0.1:${p}`;
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(`${base}/api/vision/status`)).ok) return { base, dir, child, log }; } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  child.kill();
  throw new Error("The backend did not start:\n" + log.join(""));
}

(async () => {
  if (!fs.existsSync(path.join(ROOT, "frontend", "dist", "index.html"))) {
    console.error("Build the web app first: cd frontend && npm run build");
    process.exit(2);
  }
  const only = process.argv[2];
  const browser = await chromium.launch(process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {});
  let failed = 0, ran = 0;
  for (const [name, fn] of Object.entries(tests)) {
    if (only && !name.includes(only)) continue;
    ran++;
    const server = await startServer();
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const problems = [];
    page.on("pageerror", (e) => problems.push(`page error: ${e.message}`));
    page.on("console", (m) => m.type() === "error" && !/Failed to load resource/.test(m.text()) && problems.push(`console: ${m.text()}`));
    const shot = async (label) => SHOTS && page.screenshot({ path: path.join(SHOTS, `${name.replace(/\W+/g, "-")}-${label}.png`), fullPage: true });
    try {
      await fn({ page, base: server.base, shot, fixtures: path.join(__dirname, "fixtures") });
      if (problems.length) throw new Error(problems.join("\n"));
      if (server.log.some((l) => /Traceback|Internal Server Error/.test(l))) throw new Error("server error:\n" + server.log.join(""));
      console.log(`PASS  ${name}`);
    } catch (e) {
      failed++;
      console.log(`FAIL  ${name}\n      ${String(e.message).split("\n").join("\n      ")}`);
      await shot("FAILED");
    } finally {
      await page.close();
      server.child.kill();
      await new Promise((r) => setTimeout(r, 150));
      fs.rmSync(server.dir, { recursive: true, force: true });
    }
  }
  await browser.close();
  console.log(`\n${ran - failed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
