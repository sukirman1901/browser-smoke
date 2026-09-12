#!/usr/bin/env node
import { execSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync, mkdirSync, cpSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PKG_DIR = join(__dirname, "..");
const CWD = process.cwd();
const HOME = process.env.HOME || process.env.USERPROFILE || "/root";
const OCODE_GLOBAL_DIR = join(HOME, ".config", "opencode");
const HOSTS = ["opencode", "cursor", "claude"];

function ask(question) {
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => rl.question(question, (a) => { rl.close(); resolve(a.trim().toLowerCase()); }));
}

function sh(cmd, opts = {}) {
  console.log(`> ${cmd}`);
  return execSync(cmd, { stdio: "inherit", ...opts });
}

function readJson(path) {
  if (!existsSync(path)) return {};
  try { return JSON.parse(readFileSync(path, "utf-8")); } catch { return {}; }
}

function writeJson(path, obj) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(obj, null, 2) + "\n");
}

function getPythonCmd() {
  const candidates = ["python3.12", "python3.11", "python3.10", "python3", "python"];
  for (const cmd of candidates) {
    try {
      const ver = execSync(`${cmd} --version`, { stdio: "pipe" }).toString().trim();
      const match = ver.match(/Python (\d+)\.(\d+)/);
      if (match) {
        const [major, minor] = [parseInt(match[1]), parseInt(match[2])];
        if (major > 3 || (major === 3 && minor >= 10)) return cmd;
      }
    } catch { /* skip */ }
  }
  console.error("❌ Python 3.10+ not found. Install Python 3.10 or newer first.");
  process.exit(1);
}

function stdMcpEntry(venvDir, mcpDir) {
  return {
    command: join(venvDir, "bin", "python3"),
    args: ["-m", "server"],
    cwd: mcpDir,
  };
}

function installSkill(dir) {
  const skillsDir = join(dir, "skills", "browser-smoke");
  mkdirSync(skillsDir, { recursive: true });
  const skillSrc = join(PKG_DIR, "skills", "browser-smoke", "SKILL.md");
  if (existsSync(skillSrc)) {
    writeFileSync(join(skillsDir, "SKILL.md"), readFileSync(skillSrc, "utf-8"));
  }
}

function writeOpenCode(scope, venvDir, mcpDir) {
  const isGlobal = scope === "global";
  const configDir = isGlobal ? OCODE_GLOBAL_DIR : CWD;
  const configPath = join(configDir, "opencode.json");
  const config = readJson(configPath);
  if (!config.mcp) config.mcp = {};
  config.mcp["browser-smoke"] = {
    type: "local",
    command: [join(venvDir, "bin", "python3"), "-m", "server"],
    cwd: mcpDir,
  };
  writeJson(configPath, config);
  installSkill(configDir);
  console.log(`   ✅ OpenCode: ${configPath}`);
}

function writeCursor(scope, venvDir, mcpDir) {
  const isGlobal = scope === "global";
  const configPath = isGlobal
    ? join(HOME, ".cursor", "mcp.json")
    : join(CWD, ".cursor", "mcp.json");
  const config = readJson(configPath);
  if (!config.mcpServers) config.mcpServers = {};
  config.mcpServers["browser-smoke"] = stdMcpEntry(venvDir, mcpDir);
  writeJson(configPath, config);
  installSkill(isGlobal ? join(HOME, ".cursor") : join(CWD, ".cursor"));
  console.log(`   ✅ Cursor: ${configPath}`);
}

function writeClaude(scope, venvDir, mcpDir) {
  const isGlobal = scope === "global";
  const configPath = isGlobal
    ? join(HOME, ".claude.json")
    : join(CWD, ".mcp.json");
  const config = readJson(configPath);
  if (!config.mcpServers) config.mcpServers = {};
  config.mcpServers["browser-smoke"] = stdMcpEntry(venvDir, mcpDir);
  writeJson(configPath, config);
  installSkill(isGlobal ? join(HOME, ".claude") : join(CWD, ".claude"));
  console.log(`   ✅ Claude Code: ${configPath}`);
}

function parseHosts(args) {
  const selected = HOSTS.filter((h) => args.includes(`--${h}`));
  if (args.includes("--all")) return [...HOSTS];
  if (selected.length) return selected;
  return null;
}

async function main() {
  const args = process.argv.slice(2);
  const isPrint = args.includes("--print");
  const flagScope = args.includes("--global") ? "global" : args.includes("--local") ? "local" : null;

  console.log(`
╔══════════════════════════════════════╗
║   Browser Smoke MCP - Setup         ║
╚══════════════════════════════════════╝
`);

  const python = getPythonCmd();

  let scope = flagScope;
  if (!scope && !isPrint) {
    const answer = await ask(`
Pilih lokasi instalasi:

  [1] Global
  [2] Local (project ini)
  [3] Cancel

Pilih [1/2/3]: `);
    if (answer === "3" || answer === "c" || answer === "cancel") {
      console.log("\n❌ Dibatal.");
      process.exit(0);
    }
    scope = answer === "1" || answer === "g" || answer === "global" ? "global" : "local";
  } else if (!scope) {
    scope = "local";
  }

  let hosts = parseHosts(args);
  if (!hosts && !isPrint) {
    const answer = await ask(`
Pilih host MCP:

  [1] OpenCode
  [2] Cursor
  [3] Claude Code
  [4] All

Pilih [1/2/3/4]: `);
    if (answer === "2") hosts = ["cursor"];
    else if (answer === "3") hosts = ["claude"];
    else if (answer === "4") hosts = [...HOSTS];
    else hosts = ["opencode"];
  } else if (!hosts) {
    hosts = ["opencode"];
  }

  const isGlobal = scope === "global";
  const targetDir = isGlobal ? join(OCODE_GLOBAL_DIR, ".browser-smoke") : join(CWD, ".browser-smoke");
  const mcpDir = join(targetDir, "mcp");
  const venvDir = join(targetDir, ".venv");

  console.log(`\n📍 ${isGlobal ? "Global" : "Local"} · hosts: ${hosts.join(", ")}`);

  if (isPrint) {
    console.log(JSON.stringify(stdMcpEntry(venvDir, mcpDir), null, 2));
    process.exit(0);
  }

  console.log("\n📦 Syncing MCP server files...");
  mkdirSync(targetDir, { recursive: true });
  cpSync(join(PKG_DIR, "mcp"), mcpDir, { recursive: true });

  if (!existsSync(join(venvDir, "bin", "python3"))) {
    console.log("\n📦 Creating Python virtual environment...");
    sh(`${python} -m venv "${venvDir}"`);
    console.log("\n📦 Installing Python dependencies...");
    sh(`"${join(venvDir, "bin", "pip")}" install -r "${join(mcpDir, "requirements.txt")}"`);
    console.log("\n📦 Installing Playwright browser (Chromium)...");
    sh(`"${join(venvDir, "bin", "playwright")}" install chromium`);
  } else {
    console.log("\n✅ Virtual environment already exists. Skipping.");
  }

  console.log("\n📝 Writing MCP config...");
  if (hosts.includes("opencode")) writeOpenCode(scope, venvDir, mcpDir);
  if (hosts.includes("cursor")) writeCursor(scope, venvDir, mcpDir);
  if (hosts.includes("claude")) writeClaude(scope, venvDir, mcpDir);

  console.log(`
╔══════════════════════════════════════╗
║   ✅ Setup complete                  ║
║   Restart the MCP host(s)            ║
╚══════════════════════════════════════╝
`);
}

main().catch((err) => {
  console.error("\n❌ Setup failed:", err.message);
  process.exit(1);
});
