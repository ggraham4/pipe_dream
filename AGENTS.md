# AGENTS.md — start here

This file is auto-loaded by AI assistants. It holds exactly two things:
Gabe's standing constraints, copied verbatim, and a pointer to the
current-state document.

**Read [`README.md`](README.md) next.** It is the single, consolidated
description of the project as it stands now: what's live, what works,
what's a dead end, what's in flight on which branch, open decisions for
Gabe, the repo map, reproduction and the landmines to know before adding
a feature. The long narrative this file used to carry (workstreams,
Rounds 9-19, known gaps, future plans) now lives there, or survives as
history via `git show 29eb67b:AGENTS.md`.

Maintained by the `pipe-dream-readme-manager` agent (since 2026-09-23).
Don't edit this file or README.md directly; send your results doc to that
agent. Parallel-session rules (the ledger, Rule 0 on git, app ownership)
live outside the repo in `~/.claude/CLAUDE.md` and
`~/.claude/pipe_dream-coordination/LEDGER.md`.

**Owner: Gabe.** All modeling decisions, scope calls, and the standing
constraints below are his; treat this file and the other project docs as
recording *his* decisions, not a spec to freely deviate from.

## Standing constraints — read before touching anything

1. **Never push to / redeploy the live app without Gabe's explicit,
   in-the-moment permission**, even if a change looks obviously correct or
   beneficial. This has been an explicit standing instruction throughout
   this project's development. If you're an AI assistant and unsure
   whether a change would affect the live app, ask first.
2. **Don't run destructive git operations** (`push --force`, `reset --hard`,
   history rewrites) without explicit request, and never on `main` without
   being asked.
3. **Treat `.gitignore`'d paths as regenerable, not disposable-without-
   thought.** Most of them are — exact commands are below. A couple are
   flagged as **not currently reproducible** (see "Known gaps" below) —
   don't delete those assuming a script will rebuild them, because none
   currently will.
4. This is a solo research project that occasionally gets outside review —
   Gabe mentioned (2026-08-30) a colleague is independently building a
   similar stock-picking project with a different model architecture and
   different input variables. If you're helping compare notes with that
   project or its outputs, don't assume this repo's specific choices
   (feature set, horizon, universe) are the only reasonable ones — they're
   this project's choices, arrived at empirically and documented as such
   throughout, not a claim that they're optimal in general.
5. **`git add`/`git commit`/`git push` are fine to run yourself, on your
   own judgment (changed 2026-09-17, per Gabe — previously this required
   handing files to him to run manually).** This does NOT loosen anything
   else: constraint #1 (never push/redeploy the *live app*) and constraint
   #2 (no destructive ops — force-push, `reset --hard`, history rewrites —
   without explicit request) both still stand exactly as before, including
   pushing/merging to `main`, which still needs Gabe's in-the-moment
   go-ahead like any other main-branch or deploy action. Keep `.gitignore`
   doing its job — don't commit large/regenerable files (see the
   reproduction table below); everything currently gitignored should stay
   that way unless there's a specific reason to change it.
6. **Never store live API keys/secrets in any file that lives inside this
   git repo** (`SHARADAR_API_KEY` included) — those belong only in
   whatever out-of-repo secrets store this project's owner uses (e.g. the
   Claude Project's own docs, kept separate from git), never committed.

## Where to go next

- [`README.md`](README.md) — current state, in flight, open conflicts, repo
  map, reproduction, landmines, doc index, superseded claims.
- [`DATA-PIPELINE-HANDOFF.md`](DATA-PIPELINE-HANDOFF.md) — the point-in-time
  data layer. Read it before touching `final/data/sharadar/`.
- [`final/src/reset2026/PREREGISTRATION.md`](final/src/reset2026/PREREGISTRATION.md)
  — pre-register there (or in a dated doc) before running any composite
  experiment.
- [`final/src/sweep/RUNBOOK.md`](final/src/sweep/RUNBOOK.md) — the XGBoost-era
  sweep harness and its feature-admission gate.
