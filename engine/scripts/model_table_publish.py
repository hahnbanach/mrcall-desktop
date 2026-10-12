"""The daily model-table job's last step: publish, or settle alone (`model_table_job.py`, step 6).

`Publish` is the part of the job's `Run` that writes to the data branch at
the end of a run: one commit holding the new record, the run's settlement
and the pruned `results.json` (`model_table_results.prune`); or, for a run
that cannot publish, its settlement and every paid result it holds, so that
neither its spend nor what it bought is lost.
"""

from __future__ import annotations

import hashlib
import json

import model_table_decide as decide
import model_table_records as records
import model_table_results as results_of
import resolve_models as rm

STAMP = records.STAMP


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Publish:
    """`Run`'s publication (module docstring); it reads `s`, `spend`,
    `edges`, `ctx`, `roles`, `now`, `dry_run`, `results` and `published`
    (the data branch's files as the run read them) from the run."""

    def _results_text(self) -> str | None:
        """`results.json` as the run holds it, or None when it is the
        published file unchanged (nothing to push)."""
        if self.results is None:
            return None
        text = records.dump(self.results)
        before = self.published.get("results.json")
        if before is None and not self.results["results"]:
            return None
        return None if before == text.encode("utf-8") else text

    def _settle_alone(self) -> None:
        """Push the settlement by itself, with the paid results (a run that cannot publish)."""
        text = self.spend.settled() if self.spend is not None else None
        if text is None:
            return
        files = {"ledger.json": text}
        held = self._results_text()
        if held is not None:
            files["results.json"] = held
        try:
            message = (
                f"model-table: run {self.spend.run} settles USD {records.usd(self.spend.consumed)}"
            )
            self.edges.push(files, message)
        except Exception as err:  # noqa: BLE001 - its reservation stays counted in full
            self.s["problems"].append(f"the settlement could not be pushed: {err}")

    def _finish(self, rec: dict, snap: dict, d: dict) -> None:
        """Publish, or fail with the last published record kept."""
        problems = list(d["problems"])
        self.s["notes"] += d["notes"]
        files, table = {}, rec["table"]
        if not problems:
            try:
                files, table = self._files(rec, snap, d)
            except rm.gates.GateError as err:
                problems.append(str(err))
        changes = decide.snapshot_changes(rec["snapshot"], snap, table)
        self.s["snapshot"], self.s["empty_anthropic"] = changes
        if problems:
            self.s["problems"] += problems
            if not self.dry_run:
                self._settle_alone()
            return
        if self.dry_run:
            self.s.update(status=f"dry run: would publish {', '.join(sorted(files))}", code=0)
            return
        settled = self.spend.settled()
        if settled is not None:
            files["ledger.json"] = settled
        if all(rec["published"].get(n) == text.encode("utf-8") for n, text in files.items()):
            self.s.update(status="unchanged: nothing to publish", code=0)
            return
        changed = "decision changed" if "table.json" in files else "snapshot only"
        message = f"model-table: {changed}; snapshot {snap['version']}"
        self.edges.push(files, message)
        self.s.update(status=f"published ({changed})", code=0)

    def _files(self, rec: dict, snap: dict, d: dict) -> tuple[dict, dict]:
        """The files to publish and the table in force after them."""
        measured, source = self.ctx["measured"], rec["published"].get("measured.json")
        source = source if source is not None else (self.roles / "measured.json").read_bytes()
        unchanged = measured == json.loads(source)
        text = source.decode("utf-8") if unchanged else records.dump(measured)
        stamps = {
            "resolved_at": self.now.strftime(STAMP),
            "catalogue_read_at": snap["read_at"],
            "requirements_sha256": _sha(rec["req_bytes"]),
            "measured_sha256": _sha(text.encode("utf-8")),
        }
        fresh = rm.resolver.document(d, stamps)
        lines = rm.differences(rm.resolver.decision(rec["table"]), rm.resolver.decision(fresh))
        self.s["decision"] = lines
        table = fresh if lines else rec["table"]
        rm.gates.check_table(table, rec["req"], snap)
        published = rec["published"]
        files = {"snapshot.json": rm.gates.dump(snap, 2) + "\n"}
        if lines or published.get("table.json") is None:
            files["table.json"] = rm.gates.dump(table, 4) + "\n"
        if published.get("measured.json") is None or not unchanged:
            files["measured.json"] = text
        self.results = results_of.prune(self.results, measured, self.ctx["hashes"])
        pruned = self._results_text()
        if pruned is not None:
            files["results.json"] = pruned
        return files, table
