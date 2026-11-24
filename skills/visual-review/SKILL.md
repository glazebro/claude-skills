---
name: visual-review
description: Drive a real, visible browser through the UI changes in the current branch so a human can watch the change work end to end, live. Use whenever the user wants to SEE their work rather than read about it — "visual review", "walk me through the PR", "show me my UI changes", "open the browser and click through what changed", "tour the changes". It works out which screens the diff touches, maps them to URLs, logs in as the right role, and runs a throwaway headed Playwright script that visits each screen slowly with an on-screen caption, exercises every changed behavior, takes before-and-after screenshots for anything that changes existing output, and holds the window open at the end. It also collects UX findings (console and page errors, failed requests, and screenshots it reviews for layout and accessibility problems). Pass `--fix` to fix the findings; with no argument it reports them and asks how to proceed. Not for writing a permanent test, and not for a headless pass/fail check.
---

The argument is: $ARGUMENTS

# Visual review

A **live, watchable review**: a real Chromium window opens, navigates through exactly the screens this branch changed, moves slowly enough for a human to follow, captions each one ("now showing: …"), and stays open at the end. Along the way it captures UX findings, then either fixes them (`--fix`) or asks what to do with them. It is a demo and a UX pass, not an automated test.

If the branch has **no UI-facing changes** (backend, migrations, tests or tooling only), say so and stop: there is nothing to watch.

Tell the user up front: the review covers the current branch's diff against the default branch, run **locally**, and it is headed and slowed down on purpose because a human is watching.

## 0. Preflight

Check that Playwright resolves from the project:

```bash
node -e "require.resolve('@playwright/test')" 2>/dev/null && echo "playwright: present" || echo "playwright: MISSING"
```

- **Missing** — stop and ask before installing anything; never add a dependency silently. If the user declines, fall back to a live tour with a browser MCP server, which only works for public pages.
- **Present** — run `npx playwright install chromium` (idempotent; it downloads a browser, not a code dependency).

Read the convention docs (`AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`) for the dev-server command and port, the check command, how test logins work, and where routes are defined.

## 1. Find what changed

```bash
git fetch origin
BASE=$(git merge-base origin/<default branch> HEAD)
git diff "$BASE" HEAD --name-only
```

Keep only files that affect what a user sees: pages, layouts, components, styles that change rendered output, and server code whose effect shows on a screen. List the rest as "not part of the tour". Then read the hunks of every file you kept: one file can add a field, change a default and fix a bug at once.

## 2. Map changes to screens and URLs

This is judgment at run time, not a lookup table. If the project centralizes its routes (a routes file, a router config), use it as the feature-to-URL map. Otherwise read the router.

- A changed **page or route** maps to its URL directly.
- A changed **shared component** (header, nav, a widget) maps to one representative page that renders it; mention that it appears elsewhere too.
- A changed **component that has no URL of its own** (an editor block, a modal) maps to the screen with the least setup that renders it.
- A changed **flow** (sign-up, checkout) is walked step by step in order.

If you cannot tell which screen shows a change, ask one targeted question rather than touring the wrong screen.

## 2a. Cover everything the diff touched

Turn the kept hunks into a **coverage checklist**: one line per user-visible behavior the diff adds or changes. Every line needs a stop that proves it, and the final report ticks each one off or says which were not covered and why.

- **Exercise it, don't just look at it.** If the change is an interaction, the stop performs it (click, choose, upload a real file, submit) and asserts the result the user relies on, not only that the screen looks plausible.
- **Before and after for anything that changes existing output.** When the diff alters how something already saved or live renders (a restyle, a changed default, a data conversion, a bug fix), capture the same screen on the default branch and on this branch, at a desktop and a phone width. To get the default-branch side, add a worktree at `$BASE` in a uniquely named scratch folder, provision it like a fresh checkout with its own database and port so branch data cannot leak into the baseline, run the same script against it with `WALKTHROUGH_SIDE=before`, then tear the worktree and its services down. Brand-new screens have no "before"; skip the pair there.
- **Use real data shapes,** not only a fresh fixture: saved records as they actually exist are what break.
- **When the user reports a bug the tour didn't show,** find the input that triggers it and add that as a stop instead of concluding it is fixed.

## 3. Pick the logins

Each screen is gated by who is logged in. Reuse the project's saved test logins (for example Playwright `storageState` files under its e2e folder); the convention docs or the e2e config say where they live and how to regenerate them. The script creates a **fresh context per role**, so one run can tour screens for several roles.

## 4. Make sure a dev server is up

Check whether the project's dev server is already listening on its port (`lsof -nP -iTCP:<port> -sTCP:LISTEN`). Reuse it if so. If not, tell the user, including how long startup takes if seeding is slow, and let them start it; do not boot it silently in the background.

## 5. Write and run the headed walkthrough

Write a **throwaway** script to a scratch folder **outside the repo** (`mktemp -d`), never into the test folder, so the suite and CI never pick it up. Adapt the `tour` array per run:

```ts
import { mkdir, writeFile } from "node:fs/promises";
import { chromium, type Page } from "@playwright/test";

const BASE_URL = process.env.WALKTHROUGH_BASE_URL ?? "http://localhost:3000";
const SLOW_MO = Number(process.env.WALKTHROUGH_SLOWMO ?? 700);
const OUT_DIR = process.env.WALKTHROUGH_OUT ?? ".";
const SIDE = process.env.WALKTHROUGH_SIDE === "before" ? "before" : "after";
const AUTH: Record<string, string | undefined> = {
  // role name -> saved login file, from the project's e2e setup; "public" means logged out
  public: undefined,
};

type Stop = {
  caption: string;
  role: string;
  path: string;
  viewport?: { width: number; height: number };
  act?: (page: Page) => Promise<void>;
  actBefore?: (page: Page) => Promise<void>;
  branchOnly?: boolean;
};

const tour: Stop[] = [
  // { caption: "Settings — new notifications toggle", role: "admin", path: "/settings",
  //   act: async (page) => { await page.getByRole("switch", { name: "Email me" }).click(); } },
];

const findings: { stop: string; kind: string; detail: string }[] = [];
const manifest: { index: number; caption: string; role: string; path: string; screenshot: string }[] = [];
let currentStop = "(startup)";

function watch(page: Page) {
  page.on("console", (m) => m.type() === "error" && findings.push({ stop: currentStop, kind: "console", detail: m.text() }));
  page.on("pageerror", (e) => findings.push({ stop: currentStop, kind: "pageerror", detail: e.message }));
  page.on("requestfailed", (r) => findings.push({ stop: currentStop, kind: "requestfailed", detail: `${r.method()} ${r.url()}` }));
  page.on("response", (r) => r.status() >= 400 && findings.push({ stop: currentStop, kind: `http ${r.status()}`, detail: r.url() }));
}

async function caption(page: Page, text: string) {
  await page.evaluate((label) => {
    let el = document.getElementById("__walkthrough__");
    if (!el) {
      el = document.createElement("div");
      el.id = "__walkthrough__";
      el.style.cssText = "position:fixed;left:16px;bottom:16px;z-index:2147483647;max-width:60vw;padding:10px 14px;border-radius:8px;background:rgba(17,17,17,.92);color:#fff;font:600 14px/1.4 system-ui,sans-serif;pointer-events:none";
      document.body.appendChild(el);
    }
    el.textContent = label;
  }, text);
}

await mkdir(OUT_DIR, { recursive: true });
const browser = await chromium.launch({ headless: false, slowMo: SLOW_MO });
try {
  let key: string | null = null;
  let context = await browser.newContext();
  let page = await context.newPage();
  for (const [i, stop] of tour.entries()) {
    if (SIDE === "before" && stop.branchOnly) continue;
    currentStop = stop.caption;
    const nextKey = `${stop.role}:${JSON.stringify(stop.viewport ?? null)}`;
    if (nextKey !== key) {
      await context.close();
      context = await browser.newContext({
        storageState: AUTH[stop.role],
        ...(stop.viewport && { viewport: stop.viewport, isMobile: true, hasTouch: true }),
      });
      page = await context.newPage();
      watch(page);
      key = nextKey;
    }
    const shot = `${OUT_DIR}/shot-${String(i).padStart(2, "0")}.png`;
    try {
      await page.goto(`${BASE_URL}${stop.path}`, { waitUntil: "domcontentloaded" });
      await caption(page, `▶ ${stop.caption}`);
      await page.waitForTimeout(1500);
      const act = SIDE === "before" ? stop.actBefore : stop.act;
      if (act) await act(page);
      await page.waitForTimeout(2500);
    } catch (e) {
      findings.push({ stop: stop.caption, kind: "assertion", detail: e instanceof Error ? e.message : String(e) });
    }
    await page.screenshot({ path: shot, fullPage: true }).catch(() => {});
    manifest.push({ index: i, caption: stop.caption, role: stop.role, path: stop.path, screenshot: shot });
  }
  await caption(page, "✓ Walkthrough complete — the window stays open. Close it when you're done.");
  await page.waitForEvent("close", { timeout: 0 });
} finally {
  await writeFile(`${OUT_DIR}/manifest.json`, JSON.stringify(manifest, null, 2));
  await writeFile(`${OUT_DIR}/findings.json`, JSON.stringify(findings, null, 2));
  await browser.close();
}
```

Run it with whatever TypeScript runner the project uses (`npx tsx`, `bun`, or `node --experimental-strip-types`):

```bash
SCRATCH="$(mktemp -d)"
WALKTHROUGH_BASE_URL="http://localhost:<port>" WALKTHROUGH_OUT="$SCRATCH" npx tsx "$SCRATCH/walkthrough.ts"
```

A failing stop is recorded and the tour carries on, so one defect never hides the rest. Tune the pace with `WALKTHROUGH_SLOWMO` and the dwell times.

## 6. Narrate alongside the browser

While it runs, tell the user what each stop demonstrates and which changed files it covers. List the changed files that were not part of the tour, so coverage is honest.

## 7. Compile the UX findings

1. **`findings.json`** — console errors, page errors, failed requests and HTTP errors per stop. A page error or failed request is almost always a real defect.
2. **The screenshots** — read each `shot-NN.png` (with `manifest.json`) and judge it as a designer would: clipped or overflowing content, overlap or misalignment, broken images, poor contrast, missing focus states, layout problems at that width, placeholder copy, blank empty states.

For each finding give the screen, what is wrong, severity (blocker, should-fix, nit) and the changed file most likely responsible. Separate what **this branch introduced** from what was already there, and lead with the former. A clean review is a valid outcome; don't manufacture nits.

## 8. Act on the findings

- **`--fix`** — fix every finding you can resolve confidently in the changed code. List anything skipped and why (pre-existing, a subjective call, or unclear intent). Then run the project's check command and re-run the tour to confirm.
- **No argument** — present the findings and ask how to proceed (these combine): fix them now; post inline PR review comments with `gh` (needs a pushed branch with an open PR); write a findings report or open issues; or something else that fits this PR. Confirm before anything outward-facing, since comments and issues post publicly.

## Don't

- Don't write the walkthrough into the test folder or name it `*.test.ts`.
- Don't run it headless; the point is that a human watches.
- Don't start a slow dev server silently and leave the user waiting.
- Don't tour screens the diff didn't touch.
- Don't call a change verified because its screen rendered: every checklist item needs a stop that exercises it.
