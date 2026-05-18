#!/usr/bin/env node
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const packageRoot = dirname(scriptDir);
const invokedAs = basename(process.argv[1] || "dictate-install");
const firstArg = process.argv[2] || "";

let command = "install";
let passthrough = process.argv.slice(2);
if (invokedAs.includes("update")) {
  command = "update";
} else if (invokedAs.includes("uninstall")) {
  command = "uninstall";
} else if (["install", "update", "uninstall", "wizard"].includes(firstArg)) {
  command = firstArg;
  passthrough = process.argv.slice(3);
}

const isWindows = process.platform === "win32";
const scripts = isWindows
  ? {
      install: ["powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", join(packageRoot, "install.ps1")]],
      update: ["powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", join(packageRoot, "update.ps1")]],
      uninstall: ["powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", join(packageRoot, "uninstall.ps1")]],
      wizard: ["powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", join(packageRoot, "install.ps1"), "-Wizard"]],
    }
  : {
      install: ["bash", [join(packageRoot, "install.sh")]],
      update: ["bash", [join(packageRoot, "update.sh")]],
      uninstall: ["bash", [join(packageRoot, "uninstall.sh")]],
      wizard: null,
    };

const selected = scripts[command];
if (!selected) {
  console.error(`dictate ${command} is not supported on ${process.platform}`);
  process.exit(2);
}

const [exe, args] = selected;
const result = spawnSync(exe, [...args, ...passthrough], { stdio: "inherit" });
if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
