# Azure DevOps Ticket → PR Workflow

End-to-end pipeline for taking an Azure DevOps work item from "investigate" to "PR open against develop". Derived from a real session on this repo. Follow the phases in order; do not skip the plan-mode and review phases.

## Prerequisites (verify once per machine)

- `az --version` → Azure CLI installed.
- `az extension list --query "[?name=='azure-devops']"` → azure-devops extension installed.
- `az devops configure --list` → `organization` and `project` set; if not: `az devops configure --defaults organization=https://dev.azure.com/<org> project=<project>`.
- Git remote points at Azure DevOps (`git remote -v`). On Windows the path likely contains `Product%20Development` — work items and the repo may live in **different** ADO projects, which matters for cross-project work-item links.

## Phase 1 — Fetch the ticket

```bash
az boards work-item show --id <N> --output json
```

Parse and report back to the user:
- Title, type (Task/Bug/User Story), state, priority, area path, sprint.
- Assignee, creator, parent work item.
- Description (HTML — strip tags when summarizing).
- History/latest comment (often contains stakeholder confirmation).
- Attachment URLs.

### Image attachments

ADO returns `<img src="https://dev.azure.com/<org>/<projectId>/_apis/wit/attachments/<guid>?fileName=...">` inside the description HTML. Download with:

```bash
az rest --method get \
  --uri "<attachment URL>&api-version=7.1" \
  --resource "499b84ac-1321-427f-aa17-267ca6975798" \
  --output-file ".tmp-ticket-<N>.png"
```

Then use the `Read` tool on the file — Claude renders it. Delete `.tmp-ticket-*` files at end of session.

## Phase 2 — Plan mode

**Do not skip.** Even for a "small" UI tweak, enter plan mode after Phase 1.

1. Launch one or more `Explore` subagents (in parallel if scope is unclear) to locate the relevant components and existing patterns. Tell each agent the ticket context and ask for **file paths, line numbers, and code excerpts** — not generic descriptions.
2. Read the critical files identified by the agent(s).
3. Use `AskUserQuestion` to resolve genuine ambiguity before writing the plan. Examples of valid clarifications: scope (which surfaces?), placement (inside vs adjacent to chip?), copy. Do **not** ask "is my plan ready" — that's what `ExitPlanMode` is for.
4. Write the plan to the plan file. Include: Context, Approach, Files to modify with paths + line numbers, Why-not (alternatives rejected), Verification steps.
5. `ExitPlanMode` to request approval.

## Phase 3 — Implement

Follow the approved plan. Track progress with `TodoWrite`. Notable tactics that paid off in past sessions:

- **Centralize constants.** A new `audienceTooltip.ts`-style file with `LABEL_MATCH`, `TOOLTIP_TEXT`, and a shared `Align` type beats duplicating strings/types across 8 surfaces.
- **One reusable React helper.** Build the smallest possible component (`<ParentsAudienceTooltip />`) and compose it everywhere.
- **Gate matches by row + value** to avoid false positives (e.g. a year-group literally named "Parents"). Match the parent row label/key AND the chip text.
- **Mirror proven patterns** in the codebase rather than inventing new ones. `LabelWithToggletip.tsx` is a working `<Tooltip>` reference for sizing/alignment.

### Carbon `<Tooltip>` gotchas (learned the hard way)

- **`align="top-right"` is the working default in this codebase.** Plain `align="top"` can position oddly when wrapped in chips.
- **Wrapping the trigger in a `<button>` breaks open-state toggling** with `autoAlign`. Use a `<span>` wrapper, or pass the icon directly.
- **`autoAlign` requires a real layout-box reference.** If the wrapper has `display: contents` or zero dimensions, floating-ui mis-measures and renders the popover at viewport (0, 0). A `<span style="display: inline-flex">` wrapper or the icon-as-direct-child works.
- **Carbon `<Tag>` has TWO clipping layers:** outer `.cds--tag` AND inner `.cds--tag__label` (the latter adds `text-overflow: ellipsis; white-space: nowrap`). When putting a Tooltip inside a Tag, override both via `:has()`:
  ```scss
  .cds--tag:has(.my-tooltip-class),
  .cds--tag__label:has(.my-tooltip-class) {
    overflow: visible;
  }
  ```
  And inside the popover-content itself, reset `white-space: normal; word-break: break-word; max-inline-size: <safe value>;` because the popover-content also inherits `white-space: nowrap` from the Tag label.
- **Pass `className` to `<Tooltip>` directly** — Carbon merges it onto the `.cds--popover-container`, giving you a single stable anchor for SCSS overrides (popover-content width/wrap + chip overflow `:has()` selectors).
- **Vertical alignment of small icons:** match the `LabelWithToggletip` pattern — constrain both `.cds--popover-container` and `.cds--tooltip-trigger__wrapper` to the SVG's exact size with `line-height: 0; vertical-align: middle;`. Without this, the wrapper inherits the surrounding text's line-height and floats 1-2px above the text baseline.
- **For tight columns (chat panel) where the trigger sits near a container edge,** `align="bottom"` (popover drops below) or `align="bottom-right"` is more forgiving than `"top"`.

## Phase 4 — Self code review

Before opening the PR, do a structured review on your own diff:

```bash
git status --short
git diff HEAD --stat
git diff HEAD -- <changed paths>
npx tsc --noEmit --pretty false 2>&1 | grep -iE "<your changed file basenames>"
```

Check explicitly for:
- **Duplicated SCSS blocks** left over from iterative debugging.
- **Type literals duplicated across files** — extract to the shared constants module.
- **Trailing-newline missing** on SCSS files (`\ No newline at end of file` in diff).
- **Magic strings as row identifiers** (`row.label === 'Audience'`) — promote to a `const`.
- **No new test coverage** — flag it; at minimum suggest a unit test for the new helper and a negative-case test (e.g. a non-Audience row with the same literal should NOT trigger the conditional).
- **Browser-feature support** for new selectors (e.g. `:has()` needs Chrome 105+, Safari 15.4+, Firefox 121+).
- **Branch hygiene** — is the current branch clean off `develop`, or does it contain unrelated commits from previous work?

If the current branch contains unrelated commits, branch hygiene (Phase 6) is mandatory.

## Phase 5 — Manual test gate (mandatory; blocks PR)

**The PR must NOT be opened until the user has manually tested the change and explicitly confirmed it passes.** Code review (Phase 4) and typecheck do not replace this. Even pure SCSS / copy / config changes need a visual smoke test in the browser.

Produce a concrete, copy-ready manual test plan tailored to **this** ticket's diff — not a generic checklist. Print it to the user and then **stop and wait** for an explicit "tested OK" / "passed" before moving to Phase 6.

### How to derive the test steps

1. Re-read the ticket's acceptance criteria (description + history comments).
2. List the surfaces touched by the diff (`git diff HEAD --stat` → file paths → which screens/pages render them).
3. For each surface, write:
   - **Setup** — which dev command to run (`npm run dev` / `npm start`), which user role to log in as, which page/route to navigate to, any data prerequisites (e.g. "have a notice with audience = Parents").
   - **Action** — exact click/type/navigation steps.
   - **Expected** — observable result tied to the acceptance criteria (UI text, layout, network call, navigation target).
4. Always add at minimum:
   - **Happy path** — the primary scenario from the ticket.
   - **Edge cases** — empty state, long text, max length, special chars, locked/disabled states, different user roles if relevant.
   - **Regression checks** — adjacent features that share components/styles with the changed files (find via `git diff --stat` siblings). For SCSS changes, check every screen that imports the touched stylesheet.
   - **Visual verification** — for UI changes, screenshot before/after at the affected breakpoint(s).
5. If the change is i18n-sensitive, include a step in each supported locale.
6. If the change is permission-sensitive, include a step per affected role.

### Output format (print this block to the user)

```markdown
## Manual test steps — ticket #<N>

**Build:** `<dev command>`  •  **Branch:** `<current branch>`

### 1. Happy path — <one-line scenario>
- **Setup:** <role>, navigate to <route>
- **Steps:**
  1. <action>
  2. <action>
- **Expected:** <observable outcome>

### 2. Edge case — <name>
- **Setup:** …
- **Steps:** …
- **Expected:** …

### 3. Regression — <adjacent feature>
- **Setup:** …
- **Steps:** …
- **Expected:** <unchanged behavior>

### 4. Visual check (UI only)
- Screenshot <route> at <breakpoint>; compare to ticket attachment / Figma.
```

After printing, say literally: **"Please run the steps above and reply 'tested OK' (or report failures) before I open the PR."** Do not proceed.

### If the user reports a failure

- Return to Phase 3 (Implement) to fix.
- Re-run Phase 4 (Self code review) on the new diff.
- Re-issue an updated Phase 5 plan covering the regression area.
- Only after a clean "tested OK" do you continue.

### If the user explicitly waives testing

Only acceptable when the user types something unambiguous like "skip test" / "no test needed" / "không cần test". Record that they waived it in the eventual PR description's `### Test` section ("Manual test waived by author"). Never assume waiver from silence.

## Phase 6 — Branch hygiene off develop

If the current branch is NOT clean off `develop` (i.e. it has prior committed work), use this stash-based dance:

```bash
git stash push -u -m "<short description>"   # -u stashes untracked files (new files)
git checkout develop
git pull origin develop
git checkout -b <type>/<short-slug>          # e.g. feat/notice-parents-info-tooltip
git stash pop
```

Conventions:
- Branch name: `<type>/<short-slug>` where type ∈ {`feat`, `fix`, `refactor`, `chore`, `docs`}.
- Verify post-pop diff: `git diff HEAD --stat` should match the expected changeset only.

## Phase 7 — Commit

Stage **only** the intended files (no `git add -A`):

```bash
git add <space-separated explicit paths>
```

Commit using a HEREDOC for formatting:

```bash
git commit -m "$(cat <<'EOF'
<type>(<scope>): <imperative summary> (#<ticket>)

<paragraph explaining what and why>

<optional bullet list of surfaces / files / sub-changes>

Implements Azure DevOps ticket #<N>.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Title rules: conventional-commit format, sentence case, no trailing period, ≤ 72 chars.

## Phase 8 — Push

```bash
git push -u origin <branch>
```

Never `--force` to a shared branch. If push is rejected, investigate before reaching for `--force-with-lease`.

## Phase 9 — Generate the PR description

Use the structure from the `BMad:tasks:create-pr-description` skill if available, or this template:

```markdown
## Summary
<1-3 sentences: what + why. Mention the ticket.>

## Changes
### <Category 1>
- <bullet>

### <Category 2>
- <bullet>

## File Changes
| File | Additions | Deletions |
|------|-----------|-----------|
| <path> | +N | -N |

**Total:** N additions, N deletions

## File Line Changes Count
- **Total Lines Changed:** N
- **Files Modified:** N (M new, P modified)
- **Average Changes per File:** N

## Screenshot
### Result
<what reviewers should see end-to-end>

### Test
<verification steps + typecheck status>
```

Generate numbers from `git diff develop..HEAD --numstat`.

## Phase 10 — Open the PR

**Precondition:** Phase 5 (Manual test gate) must show the user's "tested OK" (or explicit waiver) in the conversation. If it isn't there, stop and return to Phase 5.

Preferred:

```bash
az repos pr create \
  --title "<title>" \
  --description "$(cat /tmp/pr-body.md)" \
  --source-branch <branch> \
  --target-branch develop \
  --output json
```

**Known failure:** `VS800075: The project with id '...' does not exist, or you do not have permission to access it.` This happens when the repo lives in a different ADO project than the one az's project list exposes (a common state in multi-project orgs where the repo URL still references a legacy project name). Git push works because SSH uses a different code path.

**Fallback:** print the direct web-UI URL for the user to paste the title + body:

```
https://dev.azure.com/<org>/<project-as-in-repo-url>/_git/<repo>/pullrequestcreate?sourceRef=<url-encoded-branch>&targetRef=develop
```

Also print the title and the markdown body in a copy-ready block. Don't attempt clipboard utilities in WSL/Linux sandboxes — they usually aren't installed; just print the block. Mention that work-item linking (#N) can be done from the web UI's right-hand panel even when the CLI `--work-items` flag fails for cross-project tickets.

## Phase 11 — Cleanup

- Delete any `.tmp-ticket-*` files in the repo root.
- Reset the TodoWrite list (or mark all completed).
- Confirm the branch and commit hash back to the user.

## Anti-patterns (do not do)

- Don't skip plan mode for "simple" UI work — the conversation that produced this skill burned 6+ iterations on a tooltip that looked trivial.
- Don't commit before the typecheck passes for your changed files.
- Don't squash work-in-progress fixes into one commit using `--amend` on a pushed branch.
- Don't pass `--no-verify` to bypass pre-commit hooks.
- Don't open the PR with the wrong base branch — always `develop` for this repo unless explicitly told otherwise.
- **Don't open the PR before the user has manually tested.** Typecheck + self-review do not substitute for a browser smoke test. Wait for an explicit "tested OK" or explicit waiver in Phase 5.
- **Don't print a generic test checklist.** Phase 5 must reference the actual surfaces touched by this diff and the ticket's acceptance criteria — not a copy-paste of "happy path / edge case / regression" headings with no content.
- Don't link a work item across projects via `--work-items` unless you've confirmed the CLI permission works for that org/project combo. It frequently doesn't.
