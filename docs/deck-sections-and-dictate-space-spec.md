# Deck as a product hub — sub-nav sections + the Dictate space

**Status:** Proposed · **Target app:** `deck.arcforge.au` (SvelteKit deck frontend + `arc_forge_console` backend) · **Also touches:** Dictate desktop client (portal link + sign-in return)

## The reframe (the core decision)

Today `deck.arcforge.au` **is** the agent deck — a Dictate user who signs in from the desktop app lands on "Your agents / New agent," which is agent-first and confusing (many Dictate users have no agents).

Reframe: **Deck is the account hub.** Because it's already a subdomain, Deck needs no top-level nav of its own. Inside Deck, **sub-navigation sections are the products/areas**:

- **Agents** — today's "Your agents" (the agent deck) becomes *one section*, not the whole thing.
- **Dictate** — a dedicated Dictate space (this spec).
- **Future:** Tools & Equipment (published Arc Forge skills), Connectors, Customizations.

So Agents is a peer of Dictate, not the container. This scales to the growing product line and gives each product a clean home.

## Domains & routing (decided)

- `deck.arcforge.au` = the app, **canonical**. `console.arcforge.au` is legacy (same backend) — use `deck.` going forward.
- **Drop the redundant `/deck` prefix.** Today `deck.arcforge.au/` already `307`s to `/deck/` — "deck" twice, a holdover from the `/deck` SvelteKit base path (`SVELTEKIT_BASE_PATH=/deck`) from its path-based origin. The frontend already has a **root build** (`build:root`, empty base path), so this is a build-flag + mount change, not a rewrite.
- Target (root-based, no `/deck`):
  ```
  deck.arcforge.au/          → /agents (signed in) or /login (not)
  deck.arcforge.au/agents    → Agents section
  deck.arcforge.au/dictate   → Dictate section
  deck.arcforge.au/login
  deck.arcforge.au/deck/*    → 301 → /*   (compat: preserve old links/sessions)
  ```
- Sections are **paths** on Deck (`/agents`, `/dictate`, future `/tools`, …) — no new subdomains, DNS, or TLS (the `deck.` cert covers every path).
- `arcforge.au/dictate` and `arcforge.au/deck` stay free on the **apex** for marketing.

### Dropping `/deck` — the work (folded into Phase 1)
1. Serve the SPA at root: `build:root` + mount at `/` instead of `/deck/{path:path}`.
2. Auth login route `/deck/login` → `/login` (also fixes the desktop `?next` target).
3. `301 /deck/* → /*` compatibility redirect.
4. Desktop client `ACCOUNT_PORTAL_URL` → `deck.arcforge.au/dictate` (root).

## The Dictate section — `deck.arcforge.au/dictate` (Phase 1 contents)

Same login, same `portal_session`, same Deck theme/components — but **agent-free**. Contains all four:

1. **Cloud Sync** (the control center) — sync **scope** (Meetings / Everything, matching the desktop selector), enable/disable status, **device list + revoke**, recovery-key management. The web home for sync.
2. **Subscription / plan** — Dictate Pro status, plan, renewal date, **manage billing** (Stripe customer portal link).
3. **Devices** — devices signed in to the account (mirrors the desktop app's list; revoke).
4. **Downloads / get the app** — install links for other machines; onboarding surface for a new user who just signed up.

## Navigation

- A **sub-nav** in the Deck shell (sidebar or top tabs): **Agents · Dictate** · (future **Tools · Connectors · Customizations**). Extensible — new products are new entries.
- Product-neutral shell; each section owns its content and empty states.
- Deep-linkable: `/dictate`, `/agents`. A Dictate user can be sent straight to `/dictate`.

## Desktop sign-in + account flows (this also fixes the current bug)

Today a cold desktop sign-in routes through `/deck/login` and dumps the user on the **agent deck**, and the sign-in doesn't actually complete (the login doesn't return to the consent screen — the `?next` gap for magic-link/Google login).

1. **Desktop *sign-in*:** browser → (if needed) an Arc-Forge login that **returns to the consent screen** for *all* login methods → "Approve sign-in for Dictate on this computer?" → approve → loopback callback → **app signed in** → "You're signed in, close this tab." The user finishes *in the app* and never sees the agent deck. (Fix: honor `?next` back to `/api/account/auth/authorize` after every login path.)
2. **"Manage account"** (from the Dictate desktop app) → opens **`deck.arcforge.au/dictate`** (the Dictate section), not the agent deck. Update the desktop client's `ACCOUNT_PORTAL_URL` from `console.arcforge.au/deck/account` → `deck.arcforge.au/dictate`.

## Theme migration

- **Now:** the Dictate section is Dictate content inside the existing Deck theme/components — *not* the collectible-card aesthetic.
- **Later:** migrate sections toward the card theme deliberately, as its own design pass, once the structure is in place.

## Phasing

- **Phase 1 (this):** sub-nav shell → **Agents** + **Dictate** sections; Dictate section = Sync + Subscription + Devices + Downloads; fix desktop login-return-to-consent; point "Manage account" at `/dictate`.
- **Phase 2+:** Tools & Equipment, Connectors, Customizations sections; card-theme migration; other products' account homes as their own sections.

## Open questions

- `/agents` vs keeping `/deck` as the agents route (redirect strategy so existing links/bookmarks survive).
- Whether the sub-nav is a left sidebar (scales to many sections) or top tabs (fewer) — recommend sidebar for extensibility.
- Auth gating is identical to the agent deck (same `portal_session`); confirm no Dictate-specific gating beyond a signed-in account.

---

*Phase 1 implemented in the `arc-forge-deck` repo (SvelteKit `/dictate` routes + sub-nav shell + login `?next`→consent) plus a one-line Dictate-client change to `ACCOUNT_PORTAL_URL`.*
