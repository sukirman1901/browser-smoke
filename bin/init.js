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

function ask(question) {
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => rl.question(question, (a) => { rl.close(); resolve(a.trim().toLowerCase()); }));
}

function sh(cmd, opts = {}) {
  console.log(`> ${cmd}`);
  return execSync(cmd, { stdio: "inherit", ...opts });
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

function getOrCreateConfig(scope) {
  const isGlobal = scope === "global";
  const configDir = isGlobal ? OCODE_GLOBAL_DIR : CWD;
  const configPath = join(configDir, "opencode.json");

  let config = {};
  if (existsSync(configPath)) {
    try { config = JSON.parse(readFileSync(configPath, "utf-8")); } catch { config = {}; }
  }
  return { config, configPath, configDir };
}

function addMcpToConfig(config, venvDir, mcpDir) {
  if (!config.mcp) config.mcp = {};
  config.mcp["browser-smoke"] = {
    type: "local",
    command: [join(venvDir, "bin", "python3"), "-m", "server"],
    cwd: mcpDir,
  };
}

function installSkill(configDir) {
  const skillsDir = join(configDir, "skills", "browser-smoke");
  mkdirSync(skillsDir, { recursive: true });
  const skillSrc = join(PKG_DIR, "skills", "browser-smoke", "SKILL.md");
  if (existsSync(skillSrc)) {
    writeFileSync(join(skillsDir, "SKILL.md"), readFileSync(skillSrc, "utf-8"));
  }
}

async function main() {
  const args = process.argv.slice(2);
  const isPrint = args.includes("--print");
  const flagScope = args.includes("--global") ? "global" : args.includes("--local") ? "local" : null;

  console.log(`
╔══════════════════════════════════════╗
║   Browser Smoke MCP - Setup         ║
║   OpenCode browser testing plugin   ║
╚══════════════════════════════════════╝
`);

  const python = getPythonCmd();

  // --- Ask scope ---
  let scope = flagScope;
  if (!scope && !isPrint) {
    const answer = await ask(`
Pilih lokasi instalasi:

  [1] Global  — untuk semua project (~/.config/opencode)
  [2] Local   — hanya project ini (./opencode.json)
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

  const isGlobal = scope === "global";
  const targetDir = isGlobal ? join(OCODE_GLOBAL_DIR, ".browser-smoke") : join(CWD, ".browser-smoke");
  const mcpDir = join(targetDir, "mcp");
  const venvDir = join(targetDir, ".venv");

  console.log(`\n📍 Instalasi: ${isGlobal ? "Global (~/.config/opencode)" : "Local (./)"}`);

  if (isPrint) {
    const { config } = getOrCreateConfig(scope);
    addMcpToConfig(config, venvDir, mcpDir);
    console.log(JSON.stringify(config.mcp["browser-smoke"], null, 2));
    process.exit(0);
  }

  // --- Install ---
  if (!existsSync(mcpDir)) {
    console.log("\n📦 Copying MCP server files...");
    mkdirSync(targetDir, { recursive: true });
    cpSync(join(PKG_DIR, "mcp"), mcpDir, { recursive: true });
  } else {
    console.log("\n✅ MCP server already installed. Skipping.");
  }

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

  // --- Config ---
  console.log("\n📝 Configuring OpenCode...");
  const { config, configPath, configDir } = getOrCreateConfig(scope);
  addMcpToConfig(config, venvDir, mcpDir);
  writeFileSync(configPath, JSON.stringify(config, null, 2) + "\n");
  console.log(`   ✅ Config written to: ${configPath}`);

  // --- Skill ---
  installSkill(configDir);
  console.log("   ✅ Skill file installed");

  console.log(`
╔══════════════════════════════════════╗
║   ✅ Setup complete!                 ║
║                                      ║
║   Restart OpenCode to use:           ║
║     browser-smoke skill + tools      ║
╚══════════════════════════════════════╝
`);
}

main().catch((err) => {
  console.error("\n❌ Setup failed:", err.message);
  process.exit(1);
});
