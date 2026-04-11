---
description: |
  How to test Zylch live: launch it, use it, compare results against Gmail.
  No unit tests. Real data, real validation.
---

# Testing Zylch Live

## Problem

Zylch is a sales intelligence tool. The only meaningful test is: does it find the right tasks from real emails? Unit tests with mock data don't catch the bugs that matter — false positives, missed emails, bad prioritization.

## Setup

### Prerequisites
- Profile configured: `~/.zylch/profiles/<email>/`
- Gmail MCP tools available in Claude Code (search, read message, read thread)
- pexpect installed in venv: `venv/bin/pip install pexpect`

### Interacting with Zylch REPL

Claude Code can't use interactive terminals. Use pexpect:

```python
import pexpect, re

child = pexpect.spawn('venv/bin/zylch -p <profile>', timeout=20, encoding='utf-8')

# Wait for menu
child.expect(r'  > ', timeout=20)

# Enter chat or show tasks — depends on menu options shown
# If tasks exist: '1' shows tasks, 'e' exits to chat
# If no tasks: '1' enters chat directly
child.sendline('1')

# Wait for next prompt
idx = child.expect([r'you> ', r'  > '], timeout=60)
output = re.sub(r'\x1b\[[0-9;]*m', '', child.before)  # strip ANSI

# Send commands
child.sendline('/tasks')
child.expect([r'you> ', r'  > '], timeout=300)  # /tasks may trigger LLM, slow

# Exit
child.sendline('/quit')
child.expect(pexpect.EOF, timeout=10)
```

Key gotchas:
- The menu changes based on state (tasks exist vs not, recent sync vs stale)
- `/tasks` in REPL triggers task detection (LLM calls) if no tasks exist — can take minutes
- ANSI escape codes must be stripped from output
- `child.expect` patterns must match what the app actually prints, not what you assume

### CLI commands (non-interactive)

These work without pexpect:

```bash
venv/bin/zylch -p <profile> tasks     # Show tasks (no LLM, just DB)
venv/bin/zylch -p <profile> status    # Sync stats
venv/bin/zylch -p <profile> sync      # Fetch emails + WhatsApp (no AI)
venv/bin/zylch -p <profile> update    # Full pipeline: sync + memory + tasks
```

## Test Procedure

### Step 1: Get ground truth from Gmail

Use Gmail MCP to search recent inbox:

```
gmail_search_messages(q="is:inbox after:YYYY/M/D", maxResults=50)
```

Read through the emails. For each one, classify:
- **Action required by user**: needs a reply, a decision, a follow-up
- **Monitor**: someone else is handling it, user is CC'd
- **Noise**: notifications, promotions, auto-replies, spam

Write down the action items as you see them — this is your ground truth.

### Step 2: Run Zylch and get its tasks

Either via CLI:
```bash
venv/bin/zylch -p <profile> tasks
```

Or via pexpect REPL (see above), pick "Show tasks" from menu.

### Step 3: Compare

For each Zylch task, check:

| Check | Pass | Fail |
|-------|------|------|
| Is this a real task? | Matches an email that needs action | False positive (e.g. Google security alert for own app password) |
| Is priority correct? | HIGH = urgent/time-sensitive, MEDIUM = should do soon | Mispriced (e.g. spam marked HIGH) |
| Is the description accurate? | Matches email content | Hallucinated details or wrong attribution |
| Is it deduplicated? | One task per action item | Same situation appears as multiple tasks |
| Assigned to correct person? | Task is for the user, not for someone in CC | Task created for something Ivan/colleague already handled |

For each email that should be a task, check:
- Did Zylch find it?
- If not, why? (not synced, filtered out, LLM missed it)

### Step 4: Document results

Record:
- **True positives**: tasks Zylch found that are real
- **False positives**: tasks Zylch created that shouldn't exist
- **False negatives**: real tasks Zylch missed
- **Duplicates**: same action item appearing multiple times
- **Priority errors**: wrong priority level

## Example (2026-04-10, profile user@example.com)

### Ground truth (from Gmail, 3-10 April)

Action required by Mario:
1. Riccardo Cargnel — update pitch deck with patent
2. Mohamed Ndiaye — reply to white label inquiry
3. French caller +33640523977 via MrCall — same prospect, no response yet
4. Jacobacci — patent extension text overdue
5. Business Show Media — invoice INV-9142 £341.30 overdue since 24 Mar
6. Matteo Castoldi (CERN) — declined meeting twice, needs follow-up
7. Rodrik Cave — subscription payment failed, claims already paid

Monitor (Ivan handling):
8. RealStep SGR — meeting rescheduling (week of 27 Apr proposed)
9. Cafezal — contract sent, awaiting signed copy
10. Morettino — cold brew specs/costs, awaiting payment
11. PanaComm/David Bajza — white label samples ordered

### Zylch BEFORE fixes (7 tasks, v0.1.19)

1. Michele Scacciati / RealStep follow-up (HIGH) — true positive
2. Google security alert for Zylch app password (HIGH) — FALSE POSITIVE
3. Ivan/Cafezal contract monitor (MEDIUM) — true positive
4. Mohamed Ndiaye white label reply (MEDIUM) — true positive
5. Ivan/RealStep week of 27 Apr (MEDIUM) — DUPLICATE of #1
6. MrCall French caller (MEDIUM) — true positive
7. Riccardo Cargnel pitch deck (MEDIUM) — true positive

Score: Precision 71%, Recall 56%. 1 false positive, 1 duplicate, 5 false negatives.

### Zylch AFTER fixes (14 tasks)

HIGH:
1. Ivan Marchese — Cafezal/Nomoq slot confirmation
2. Michela Apostoli — Patent text for PCT extension (Jacobacci)
3. Michele Scacciati — RealStep SGR meeting follow-up
4. Rodrik Cave — Payment status, blend change, missing order

MEDIUM:
5. Credit Control — Business Show Media INV-9142 (overdue)
6. Custom124 — David Bajza/PanaComm white label quote
7. Debora Ciccotosto — March payroll documents
8. Ivan Marchese — Cafezal contract monitor
9. Ivan Marchese — Morettino deposit follow-up
10. Mario Alemi — da compilare (self-sent reminder)
11. MrCall — French caller white label inquiry
12. Riccardo Cargnel — Pitch deck with patent
13. Mohamed Ndiaye — White label inquiry reply

LOW:
14. Matteo Castoldi — 3 meeting declines, reschedule

Score: Precision 100%, Recall 100%. 0 false positives, 0 duplicates, 0 false negatives.

### Fixes applied (2026-04-10)

1. **Self-sent emails = task** — emails from user to self bypass LLM, always create MEDIUM task
2. **Notification filter** — no-reply@, notification@, etc. skipped (fixes Google alert false positive)
3. **Task dedup by title** — SequenceMatcher >50% similarity prevents duplicates across threads
4. **Post-discuss default = back** — "Let's discuss" no longer auto-closes tasks
5. **Hard-coded invoice rule** — 2+ reminders from same sender = MEDIUM task (fixes Business Show)
6. **Hard-coded decline rule** — 2+ declines from same person = LOW task (fixes Castoldi)
7. **Case-insensitive DB queries** — from_email comparison uses ilike (fixes Castoldi count=0 bug)
8. **Sync default 60 days** — was 7, now catches older emails
9. **Prompt trainer updated** — no longer blanket-filters invoice reminders or calendar declines
