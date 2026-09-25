# Microsoft Store Screenshots

Captured from the current Dictate UI (dark theme) with
`design/tools/capture-store.mjs` against the mock-mode dev server. Each image
is the app window at 2x, 2112 x 1472, above the Store's 1366 x 768 minimum.
They use neutral demo dictation text and contain no user data.

Upload set:

1. `dictate-01-ready.png` - Home: click to dictate or hold Right Ctrl.
2. `dictate-02-recording.png` - Push-to-talk in progress: "Listening, release to insert".
3. `dictate-03-dictations.png` - Local dictations list for copy and recovery.
4. `dictate-04-about.png` - About: "Transcription runs on this machine. Nothing is sent anywhere."

Recapture after UI changes:

    XDG_DATA_HOME=/tmp/empty ui/node_modules/.bin/vite ui --port 5179 &
    PLAYWRIGHT=<path>/node_modules/playwright/index.mjs CHROME=/usr/bin/google-chrome \
      node design/tools/capture-store.mjs docs/msstore/assets/screenshots
