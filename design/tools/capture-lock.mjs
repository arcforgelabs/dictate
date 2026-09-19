// Usage: node design/tools/capture-lock.mjs <out-dir>  (needs a mock-mode vite dev server on :5179
// and a playwright install; point PLAYWRIGHT at it, CHROME at a Chrome binary).
const { chromium } = await import(process.env.PLAYWRIGHT || "playwright");
import fs from "node:fs";
const out = process.argv[2];
const url = "http://localhost:5179/";
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });
const manifest = { captured_at: new Date().toISOString(), url, viewport: { name: "win", width: 1200, height: 820 }, captures: [] };
const states = {
  "ready": async (p) => {},
  "recording": async (p) => { await p.click(".recbtn"); await p.waitForTimeout(900); },
  "paused": async (p) => { await p.click(".recbtn"); await p.waitForTimeout(600); await p.click(".recbtn"); await p.waitForTimeout(500); },
  "dictations": async (p) => { await p.click("button[title='Dictations']"); await p.waitForTimeout(500); },
  "meeting-note": async (p) => { await p.click("button[title='Dictations']"); await p.waitForTimeout(400); await p.click(".note-row:has-text('Speaker 1')"); await p.waitForTimeout(500); },
  "quick-note": async (p) => { await p.click("button[title='Dictations']"); await p.waitForTimeout(400); await p.click(".note-row >> nth=0"); await p.waitForTimeout(500); },
  "about": async (p) => { await p.click("button[title='About Dictate'], button[aria-label='About Dictate'], button:has-text('About')"); await p.waitForTimeout(400); },
  "palette": async (p) => { await p.keyboard.press("Control+K"); await p.waitForTimeout(400); },
};
for (const theme of ["light", "dark"]) {
  for (const [name, act] of Object.entries(states)) {
    const ctx = await browser.newContext({ viewport: { width: 1200, height: 820 }, colorScheme: theme, deviceScaleFactor: 1 });
    const p = await ctx.newPage();
    await p.goto(url); await p.waitForSelector(".titlebar"); await p.waitForTimeout(700);
    try { await act(p); } catch (e) { console.error(name, theme, "action failed:", e.message.split("\n")[0]); }
    const file = `${out}/${name}-win-${theme}.png`;
    await p.screenshot({ path: file });
    manifest.captures.push({ name: `${name}-win-${theme}`, theme, state: name, title: await p.title(), screenshot: file.replace(/^.*design\//, "design/") });
    console.log("captured", file);
    await ctx.close();
  }
}
fs.writeFileSync(`${out}/manifest.json`, JSON.stringify(manifest, null, 2));
await browser.close();
