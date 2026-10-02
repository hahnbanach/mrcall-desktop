"""Scores: the Artificial Analysis indices joined to the screen, imputed where one is missing.

Brief D2: a model with an Artificial Analysis record but no score on a
role's index (on the 2026-10-02 read, Sonnet 5.5 and Opus 5.5 have no
`agentic_index`) gets an estimate from its own intelligence index — a
least-squares line of the index on intelligence over the same read's
records that carry both (one record per slug; a slug whose records disagree
is left out, as 10a did), minus one standard deviation of the residuals (a
cautious estimate) — marked `imputed` with that standard deviation. The
deviation is the root mean square of the residuals (divided by n, not
n - 2): on the 2026-10-02 read the agentic line has n = 95, slope 1.318 and
deviation 4.69, which put Sonnet 5.5 at 57.7 and Opus 5.5 at 59.8.

A model with no record at all is never scored: it is listed as `unscored`,
so the daily report names it and it never disappears silently; it becomes
eligible as soon as it is scored. No score is ever derived from a model's
name or family. A line that cannot be fitted (fewer than `MIN_RECORDS`
records, or no spread in intelligence) imputes nothing.

Pure: the caller passes the screen (`candidates.screen`), the benchmark
records and the roster.
"""

from __future__ import annotations

import math

from .candidates import score

SCORE_SOURCE = "artificial-analysis"
INDEX_FIELDS = {
    "intelligence": "intelligence_index",
    "coding": "coding_index",
    "agentic": "agentic_index",
}
REGRESSOR = "intelligence"
MIN_RECORDS = 3


def scores_by_slug(benchmarks: list) -> tuple[dict, set]:
    """Artificial Analysis scores keyed by permaslug. A slug whose records
    disagree is returned apart, and no model is scored from it."""
    scores: dict[str, dict] = {}
    ambiguous: set[str] = set()
    for record in benchmarks:
        if not isinstance(record, dict) or record.get("source") != SCORE_SOURCE:
            continue
        slug = record.get("model_permaslug")
        if not slug:
            continue
        values = {name: score(record.get(field)) for name, field in INDEX_FIELDS.items()}
        if slug in scores and scores[slug] != values:
            ambiguous.add(slug)
        scores[slug] = values
    for slug in ambiguous:
        del scores[slug]
    return scores, ambiguous


def fit(scores: dict[str, dict], index: str) -> dict | None:
    """The least-squares line of `index` on intelligence over the records
    that carry both: `{index, n, slope, intercept, sd}`, or None when it
    cannot be fitted."""
    points = [
        (values[REGRESSOR], values[index])
        for values in scores.values()
        if values.get(REGRESSOR) is not None and values.get(index) is not None
    ]
    n = len(points)
    if n < MIN_RECORDS:
        return None
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    sxx = sum((x - mean_x) ** 2 for x, _ in points)
    if sxx == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / sxx
    intercept = mean_y - slope * mean_x
    sd = math.sqrt(sum((y - intercept - slope * x) ** 2 for x, y in points) / n)
    return {"index": index, "n": n, "slope": slope, "intercept": intercept, "sd": sd}


def estimate(line: dict, intelligence: float) -> float:
    """The cautious estimate: the line's prediction minus one deviation."""
    return line["intercept"] + line["slope"] * intelligence - line["sd"]


def scored(kept: list[dict], benchmarks: list, indices: set[str], common: dict) -> dict:
    """The candidate pool: the kept entries (`candidates.screen`) that have a
    record and every score `common.required_scores` names, each with its
    `scores` (imputed where an index of `indices` is missing) and `imputed`
    (`{index: sd}`); `unscored`, `{id: why}` for the kept entries with no
    record or no required score, in catalogue order; the `fits` used; the
    `ambiguous` slugs."""
    scores, ambiguous = scores_by_slug(benchmarks)
    fits = {index: fit(scores, index) for index in sorted(indices) if index != REGRESSOR}
    pool, unscored = [], {}
    for row in kept:
        record = scores.get(row["entry"].get("canonical_slug"))
        if record is None:
            unscored[row["id"]] = "no Artificial Analysis record"
            continue
        missing = [name for name in common["required_scores"] if record[name] is None]
        if missing:
            unscored[row["id"]] = f"no {', '.join(missing)} index"
            continue
        values, imputed = dict(record), {}
        for index, line in fits.items():
            if values[index] is None and line is not None and values[REGRESSOR] is not None:
                values[index] = estimate(line, values[REGRESSOR])
                imputed[index] = line["sd"]
        candidate = {key: value for key, value in row.items() if key != "entry"}
        pool.append({**candidate, "scores": values, "imputed": imputed})
    return {"pool": pool, "unscored": unscored, "fits": fits, "ambiguous": ambiguous}
