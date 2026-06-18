# Claude Design — Dictate mapping

The design **process** lives in skills, not here: `forge` design mode
(**Prototype Source Parity**) and the `claude-design` skill (channels,
`/design-sync`, image sharing, landing). This file is only Dictate's
project-specific mapping.

| What | Where |
| --- | --- |
| Claude Design project | `https://claude.ai/design/p/2309408a-2350-4da0-bb4c-c03c7cfee48a` (main prototype: `dictate-app/Dictate Settings.html`) |
| Design deliverables | the **`design/`** folder — organised by the design agent, mapped in [`../design/README.md`](../design/README.md). Keep it clear and discoverable; internal structure is the agent's call. |
| Production | `ui/src/` (Vite app) |
| Build / test | from `ui/`: `npm run dev` · `npm run build` · `npm test` |

**Channels (see the `claude-design` skill):** Claude Code → `/design-sync`;
Codex / Cursor / Antigravity → Claude Design → Send to Claude Code Web → GitHub
branch. Work lands on `master` (this repo's default branch); the local agent
lands it — no PR gate.

Note any deliberate prototype↔production divergences here.
