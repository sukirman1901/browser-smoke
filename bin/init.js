#!/usr/bin/env node
import { execSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync, mkdirSync, cpSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PKG_DIR = join(__dirname, "..");
const CWD = process.cwd();

function sh(cmd, opts = {}) {
  console.log(`> ${cmd}`);
  return execSync(cmd, { stdio: "inherit", ...opts });
}

function getPythonCmd() {
  try {
    execSync("python3 --version", { stdio: "ignore" });
    return "python3";
  } catch {
    try {
      execSync("python --version", { stdio: "ignore" });
      return "python";
    } catch {
      console.error("❌ Python not found. Install Python 3.8+ first.");
      process.exit(1);
    }
  }
}

function detectOcodeConfigPath() {
  const local = join(CWD, "opencode.json");
  const globalDir = join(osHomedir(), ".config", "opencode");
  const globalFile = join(globalDir, "opencode.json");

  if (existsSync(local)) return local;
  if (existsSync(globalFile)) return globalFile;
  return null;
}

function osHomedir() {
  return process.env.HOME || process.env.USERPROFILE || "/root";
}

async function main() {
  const args = process.argv.slice(2);
  const isPrint = args.includes("--print");

  console.log(`
╔══════════════════════════════════════╗
║   Browser Smoke MCP - Setup         ║
║   OpenCode browser testing plugin   ║
╚══════════════════════════════════════╝
`);

  const python = getPythonCmd();
  const installDir = join(CWD, ".browser-smoke");
  const mcpDir = join(installDir, "mcp");
  const venvDir = join(installDir, ".venv");

  if (isPrint) {
    printConfig(venvDir, mcpDir);
    process.exit(0);
  }

  // 1. Copy bundled MCP server to project
  if (!existsSync(mcpDir)) {
    console.log("\n📦 Copying MCP server files...");
    mkdirSync(installDir, { recursive: true });
    cpSync(join(PKG_DIR, "mcp"), mcpDir, { recursive: true });
  } else {
    console.log("\n✅ MCP server already installed. Skipping.");
  }

  // 2. Setup Python venv
  if (!existsSync(join(venvDir, "bin", "python3"))) {
    console.log("\n📦 Creating Python virtual environment...");
    sh(`${python} -m venv "${venvDir}"`);

    console.log("\n📦 Installing Python dependencies...");
    const pip = join(venvDir, "bin", "pip");
    sh(`"${pip}" install -r "${join(mcpDir, "requirements.txt")}"`);

    console.log("\n📦 Installing Playwright browser (Chromium)...");
    const pw = join(venvDir, "bin", "playwright");
    sh(`"${pw}" install chromium`);
  } else {
    console.log("\n✅ Virtual environment already exists. Skipping.");
  }

  // 3. Configure opencode.json
  console.log("\n📝 Configuring OpenCode...");
  let config = {};
  const configPath = detectOcodeConfigPath() || join(CWD, "opencode.json");

  if (existsSync(configPath)) {
    try {
      config = JSON.parse(readFileSync(configPath, "utf-8"));
    } catch {
      config = {};
    }
  }

  if (!config.mcp) config.mcp = {};
  if (!config.mcp.servers) config.mcp.servers = {};

  config.mcp.servers["browser-smoke"] = {
    command: join(venvDir, "bin", "python3"),
    args: ["-m", "server"],
    cwd: mcpDir,
  };

  writeFileSync(configPath, JSON.stringify(config, null, 2) + "\n");
  console.log(`   ✅ Config written to: ${configPath}`);

  // 4. Copy skill file
  const skillsDir = join(dirname(configPath), "skills", "browser-smoke");
  mkdirSync(skillsDir, { recursive: true });
  const skillSrc = join(PKG_DIR, "skills", "browser-smoke", "SKILL.md");
  if (existsSync(skillSrc)) {
    writeFileSync(join(skillsDir, "SKILL.md"), readFileSync(skillSrc, "utf-8"));
    console.log("   ✅ Skill file installed");
  }

  console.log(`
╔══════════════════════════════════════╗
║   ✅ Setup complete!                 ║
║                                      ║
║   Restart OpenCode to use:           ║
║     browser-smoke skill + tools      ║
╚══════════════════════════════════════╝
`);
}

function printConfig(venvDir, mcpDir) {
  const config = {
    mcp: {
      servers: {
        "browser-smoke": {
          command: join(venvDir, "bin", "python3"),
          args: ["-m", "server"],
          cwd: mcpDir,
        },
      },
    },
  };
  console.log(JSON.stringify(config, null, 2));
}

main().catch((err) => {
  console.error("❌ Setup failed:", err.message);
  process.exit(1);
});
