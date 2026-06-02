import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The Tauri shell loads the built assets from a file:// or tauri:// origin, so
// relative asset paths are required.
export default defineConfig({
  plugins: [react()],
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
    setupFiles: ["./src/test/setup.js"],
    css: true,
  },
});
