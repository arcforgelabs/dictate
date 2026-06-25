import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function dictateHandshakePath() {
  const dataHome = process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share");
  return path.join(dataHome, "dictate", "ui-server.json");
}

function dictateBridgePlugin() {
  return {
    name: "dictate-bridge",
    transformIndexHtml(html) {
      const handshakePath = dictateHandshakePath();
      if (!fs.existsSync(handshakePath)) return html;
      try {
        const { url, token } = JSON.parse(fs.readFileSync(handshakePath, "utf8"));
        if (!url || !token) return html;
        const script = `<script>window.__DICTATE__=${JSON.stringify({
          baseUrl: url,
          token,
          platform: "gnome",
        })}</script>`;
        return html.replace("<head>", `<head>${script}`);
      } catch {
        return html;
      }
    },
  };
}

// The Tauri shell loads the built assets from a file:// or tauri:// origin, so
// relative asset paths are required.
export default defineConfig({
  plugins: [react(), dictateBridgePlugin()],
  base: "./",
  clearScreen: false,
  build: {
    target: "es2021",
    outDir: "dist",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: [path.join(__dirname, "src/test/setup.js")],
    css: true,
  },
});
