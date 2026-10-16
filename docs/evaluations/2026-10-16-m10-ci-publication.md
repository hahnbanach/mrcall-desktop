# M10 model-table CI publication

## Actual result

[GitHub Actions run38901708899](https://github.com/hahnbanach/mrcall-desktop/actions/runs/38901708899)
completed successfully at2026-10-16T14:07:25Z on feature commit652c0007. It published
data commit `3e1273597ae74fe10c7e121c8a73996204113c9d` on `model-table`.
The repository OpenRouter secret exists and branch protection enforces admins,
linear history and no force-push/deletion while allowing normal publisher pushes.
No key value enters this record.

The exact published pair is:

- table `eaebab508662318028bf6f065b9d2a77aed554ac9b0499f6b461d395e31f2eff`;
- snapshot `7172404b072a9f3272e7e32c47ffc2a5a9df9c517c105004a02fc23884d8ec4d`,
  read_at2026-10-16T12:36:59Z.

The repository's actual `model_table_release.py --max-age-days14` passes against
the downloaded pair and candidate requirements. Its14-day boundary is
2026-10-30T12:36:59Z; later release/server builds still need a fresh check.
No wheel resource is silently replaced by this publication.

## Accounting and remaining measurements

The run records45 checks and USD0.876144, settled at14:07:15Z with no open run
reservation. It deferred661 checks because of its90-minute deadline. Success
means the admissible measured decision was published, not that every challenger
was measured. The report also retains failed, unpriced and cached cases.

October ledger count isUSD6.247792 ofUSD10. This includes the preserved
USD4.146243 recovered historical unknown maximum. It is not a provider invoice;
no old hold was deleted, reset or reclassified as a newly verified charge.
The remaining monthly allowance isUSD3.752208 under those recorded semantics.
No repeat paid proof was dispatched.

## Reproducible evidence and workflow cleanup

Protected evidence root:
`/home/mal/worktrees/.evidence/m10-execution-20261016/`.
`ci-proof-published/` retains all five exact data files, candidate requirements,
data commit and per-file hashes. `ci-proof-result.json` holds the compact result;
`ci-proof-artifacts/model-table-report/model-table-report.md` is the complete
uploaded report, SHA256
`cc83619333f1157fea2b9d7497e463535282c5d445032c4cf78d333c249d8016`.

The temporary push trigger removal is published at feature commit
`d8df989ed0b90b667a138d9b0806c1eab6dafaa1`, verified against remote workflow bytes.
This artifact checkout still contains the original proof trigger and must receive
that reviewed cleanup before main integration. Schedule05:17UTC and explicit dispatch remain unchanged,
with serialized non-cancelling execution, repository-secret-only environment and
the existing monthly cap. Four native workflow tests pass without skips; parsed
trigger inspection confirms schedule/dispatch only in that published feature.
Recheck the assembled tree before main integration.

Billing01909353 is separately deployed and passes free checks. Real paid
direct/credits acceptance, company-answer quality, current engine artifact,
ordinary operation, protected clones, canary and rollback remain independent
required gates. This CI result grants none of their missing authority.
