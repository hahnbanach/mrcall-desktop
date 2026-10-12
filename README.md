# model-table

Data branch of mrcall-desktop (milestone 10). It holds the published model
table under `v1/`:

- `table.json`: per preset and role, the ranking and the Anthropic ranking;
- `snapshot.json`: catalogue prices and request metadata;
- `measured.json`: the measured results the table was resolved from;
- `ledger.json`: the daily job's paid calls by month.

Written only by `engine/scripts/model_table_job.py` (the daily workflow
`model-resolution.yml`, or the coordinator before the desktop merge). The
first commit is the reviewed first table. A bad publish is rolled back by a
revert commit here. Engines and the billing server read
`https://raw.githubusercontent.com/hahnbanach/mrcall-desktop/model-table/v1/<file>`.
