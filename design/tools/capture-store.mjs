// Microsoft Store screenshots of the current UI, from the mock-mode dev server.
//
//   XDG_DATA_HOME=/tmp/empty ui/node_modules/.bin/vite ui --port 5179 &
//   PLAYWRIGHT=<path>/node_modules/playwright/index.mjs CHROME=/usr/bin/google-chrome \
//     node design/tools/capture-store.mjs docs/msstore/assets/screenshots
//
// Captures the app window only, at 2x, so each image is above the Store's
// 1366 x 768 minimum and inside its 3840 x 2160 limit. Mock mode uses neutral
// demo text; ?demoUpdate=off stops the demo from faking an available update.
// Meeting notes are left out: Dictate is dictation, not a meeting recorder.
const { chromium } = await import(process.env.PLAYWRIGHT || "playwright");

const out = process.argv[2];
if (!out) throw new Error("usage: node design/tools/capture-store.mjs <out-dir>");
const url = process.env.URL || "http://localhost:5179/?demoUpdate=off";
const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });

const shots = [
  ["dictate-01-ready", async () => {}],
  // Hold Right Ctrl: the push-to-talk gesture, not the long-note button.
  ["dictate-02-recording", async (p) => { await p.keyboard.down("ControlRight"); await p.waitForTimeout(1400); }],
  ["dictate-03-dictations", async (p) => { await p.click("button[title='Dictations']"); await p.waitForTimeout(500); }],
  ["dictate-04-about", async (p) => {
    await p.click("button[title='About Dictate'], button[aria-label='About Dictate'], button:has-text('About')");
    await p.waitForTimeout(400);
  }],
];

for (const [name, act] of shots) {
  const ctx = await browser.newContext({
    viewport: { width: 1366, height: 768 }, colorScheme: "dark", deviceScaleFactor: 2,
  });
  const page = await ctx.newPage();
  await page.goto(url);
  await page.waitForSelector(".titlebar");
  // The demo banner and toasts are browser-preview chrome, not the app.
  await page.addStyleTag({ content: ".demo-mode-banner, .toast, .toasts, [role='status'] { display: none !important; }" });
  await page.waitForTimeout(700);
  await act(page);
  // Keep the demo list to plain dictations; the meeting sample is out of scope.
  await page.evaluate(() => {
    document.querySelectorAll(".note-row, .dictation-row, li, [role='listitem']").forEach((el) => {
      if (/Speaker \d:/.test(el.textContent || "")) el.remove();
    });
  });
  await page.locator(".win").screenshot({ path: `${out}/${name}.png` });
  console.log(`${out}/${name}.png`);
  await ctx.close();
}
await browser.close();
