# Running Dictate on Replit

The Replit preview runs the existing React UI in standalone browser demo mode. Its dictation, history, and controls are simulated in memory; it does **not** capture or transcribe real audio or type into other applications.

The **Start application** workflow runs `cd ui && DICTATE_BROWSER_PREVIEW=1 npm run dev` on port 5000. To run it manually, use the same command. If dependencies are missing, run `cd ui && npm ci` first. The UI uses Node.js 22.

`DICTATE_BROWSER_PREVIEW=1` prevents the local engine handshake (including its bearer token) from being injected into the publicly reachable preview. Without that flag, the local live-development bridge runs on Vite's default localhost:5173.

The Python speech engine and Tauri desktop shell are not started here. Real dictation requires a local desktop session with microphone, tray, and keyboard access; see `README.md` and `ui/README.md` for desktop setup.
