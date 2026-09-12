#!/usr/bin/env node
/**
 * Runs agent JS against the Python MCP session over stdin/stdout JSON lines.
 */
import readline from "node:readline";

function send(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

function asOpts(opts) {
  if (opts == null) return {};
  if (typeof opts === "object" && !Array.isArray(opts)) return opts;
  return {};
}

let rpcId = 0;
const pending = new Map();

function rpc(method, params = {}) {
  const id = ++rpcId;
  send({ type: "rpc", id, method, params });
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
  });
}

const logs = [];
function log(...args) {
  const text = args
    .map((a) => (typeof a === "string" ? a : JSON.stringify(a)))
    .join(" ")
    .slice(0, 500);
  logs.push(text);
  send({ type: "log", text });
}

const STATES = new Set([
  "load",
  "domcontentloaded",
  "networkidle",
  "commit",
  "visible",
  "hidden",
  "attached",
  "detached",
]);

const page = {
  goto: (url, opts) => rpc("open", { url, ...asOpts(opts) }),
  click: (selector, opts) => rpc("click", { selector, ...asOpts(opts) }),
  fill: (selector, text) => rpc("type", { selector, text }),
  type: (selector, text) => rpc("type", { selector, text }),
  snapshot: (scope = "viewport") => rpc("snapshot", { scope }),
  wait: (opts) => {
    if (typeof opts === "string") {
      if (STATES.has(opts)) return rpc("wait", { state: opts });
      if (opts.includes("*") || opts.includes("://")) return rpc("wait", { url: opts });
      return rpc("wait", { selector: opts });
    }
    return rpc("wait", asOpts(opts));
  },
  evaluate: (js) =>
    rpc("execute", { js_code: typeof js === "function" ? `(${js})()` : String(js) }),
  press: (selector, key) => rpc("press", { selector, key }),
  hover: (selector) => rpc("hover", { selector }),
  scroll: (x = 0, y = 200) => rpc("scroll", { x, y }),
  reload: () => rpc("reload", {}),
  paste: (selector, text) => rpc("paste", { selector, text }),
  drag: (source, target) => rpc("drag", { source, target }),
  dialog: (action, prompt = "") => rpc("dialog", { handle: action, prompt }),
  download: (selector, saveAs = "") => rpc("download", { selector, save_as: saveAs }),
  upload: (selector, paths) =>
    rpc("set_files", {
      selector,
      paths: Array.isArray(paths) ? paths.join(",") : String(paths ?? ""),
    }),
  select: (selector, opts) => {
    if (typeof opts === "string") return rpc("select", { selector, value: opts });
    if (typeof opts === "number") return rpc("select", { selector, index: opts });
    return rpc("select", { selector, ...asOpts(opts) });
  },
  switchTab: (index) => rpc("switch_tab", { index }),
};

const open = (url, opts) => page.goto(url, opts);
const click = (selector, opts) => page.click(selector, opts);
const type = (selector, text) => page.fill(selector, text);
const snapshot = (scope) => page.snapshot(scope);
const wait = (opts) => page.wait(opts);
const execute = (js) => page.evaluate(js);
const press = (selector, key) => page.press(selector, key);
const hover = (selector) => page.hover(selector);
const scroll = (x, y) => page.scroll(x, y);
const dialog = (action, prompt) => page.dialog(action, prompt);
const download = (selector, saveAs) => page.download(selector, saveAs);
const upload = (selector, paths) => page.upload(selector, paths);
const select = (selector, opts) => page.select(selector, opts);
const switchTab = (index) => page.switchTab(index);

const rl = readline.createInterface({ input: process.stdin });

rl.on("line", async (line) => {
  let msg;
  try {
    msg = JSON.parse(line);
  } catch {
    return;
  }
  if (msg.type === "ok") {
    pending.get(msg.id)?.resolve(msg.result);
    pending.delete(msg.id);
    return;
  }
  if (msg.type === "err") {
    pending.get(msg.id)?.reject(new Error(msg.message || "rpc error"));
    pending.delete(msg.id);
    return;
  }
  if (msg.type !== "script") return;
  try {
    const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
    const fn = new AsyncFunction(
      "page",
      "open",
      "click",
      "type",
      "snapshot",
      "wait",
      "execute",
      "press",
      "hover",
      "scroll",
      "log",
      "dialog",
      "download",
      "upload",
      "select",
      "switchTab",
      msg.code,
    );
    const result = await fn(
      page,
      open,
      click,
      type,
      snapshot,
      wait,
      execute,
      press,
      hover,
      scroll,
      log,
      dialog,
      download,
      upload,
      select,
      switchTab,
    );
    send({ type: "done", result, logs });
  } catch (err) {
    send({ type: "error", message: String(err && err.message ? err.message : err), logs });
  }
  process.exit(0);
});
