# Recover billing-business selection during sandbox acceptance

R5 is blocked in the signed app: Mario Gmail's paid chat is refused at quote
with `business_id_required`, and the business picker waits on Searching then
shows no result. The intended business is the CTO's choice, never an operator
guess. Current host metadata proves missing billing selection and successful
initial list calls; it does not yet prove that the typed search reaches the
same daemon. App version/current connection confirmation is pending.

Source defects are independent of that uncertainty: displayed labels can use
companyName, nickname, personal name or surname, while free-text lookup only
searches companyName. The picker also converts non-authentication failures to
an empty result, hiding timeout/connection errors as a genuine empty search.

Repair the existing picker so it searches the displayed name fields within the
server-authorized business scope, preserves exact UUID and email routing,
deduplicates businesses by ID, bounds work and ignores stale responses. Surface
lookup failures distinctly, permit retry and never describe incomplete failed
search as no matching business. Require explicit selection and save: remove the current automatic `onChange`
when an unset picker receives a sole business. Loading, searching, retrying or
receiving one result must never change the selected billing business without
a user selection gesture. Do not
choose a different billing business, change credentials or relax server checks.

Acceptance: behavioral tests execute the actual picker, including a business
whose only match is personal name or nickname, duplicate hits, real empty
results, timeout/rejection, stale/out-of-order results, a sole result that is
not automatically selected, and explicit selection.
Typecheck/build and the existing Settings checks pass. Correlate available host
metadata without reading token/voice/mail values or printing business data.
Keep R5 active until its real app journey and representative scratch lifecycle
are accepted. Publish only scoped changes and reviewed delivery evidence under
R5; two independent final reviewers must approve before a signed patch release.

Use an isolated worktree to preserve concurrent Qonto and documentation work.
Assess the next unused patch tag at release time; do not overwrite an existing
tag or claim an already installed app has changed. Do not modify the service
checkout directly. No paid retry, live profile change or arbitrary business
selection is part of this source repair.
