"""Read a private M4 call trace without loading an engine profile or credentials.

Usage: python engine/scripts/voice_diagnostic_report.py /private/path/call-uuid.db
Output contains private test dialogue. Do not redirect it into a Git checkout.
Transcript intervals and reflected audio are not proof of handset playback.
"""

import argparse
import json
import sqlite3
from pathlib import Path


def report(path):
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        rows = [
            (seq, utc, elapsed, kind, json.loads(data))
            for seq, utc, elapsed, kind, data in db.execute(
                "SELECT seq,utc,elapsed_ms,kind,data FROM events ORDER BY seq"
            )
        ]
        has_transcript = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='transcript_deltas'"
        ).fetchone() is not None
        transcript = (
            db.execute(
                "SELECT start_ms,end_ms,role,delta FROM transcript_deltas ORDER BY seq"
            ).fetchall()
            if has_transcript else []
        )
    print("PRIVATE CALL DIAGNOSTIC — handset playback requires caller confirmation")
    if not rows:
        print("Empty trace; incomplete evidence")
        return
    print("Call:", rows[0][4]["call_id"], "Config:", rows[0][4]["config_revision"])
    print("Attached UTC:", rows[0][1])
    print("Events:", len(rows), "Trace closed:", rows[-1][3] == "trace_closed")
    print("\nTranscript (delivery order; provider timeline in milliseconds):")
    role, text, start, end = None, "", None, None
    parts = (
        [(start_ms, end_ms, current, delta)
         for start_ms, end_ms, current, delta in transcript]
        if has_transcript else [
            (data.get("start_ms"), data.get("end_ms"),
             "caller" if kind == "session.input_transcript.delta" else "voice",
             data.get("delta") or "")
            for _, _, _, kind, data in rows
            if kind in ("session.input_transcript.delta", "session.output_transcript.delta")
        ]
    )
    for part_start, part_end, current, delta in parts:
        if role != current:
            if role:
                print(f"[{start}–{end}] {role}: {text}")
            role, text, start = current, "", part_start
        text += delta
        end = part_end
    if role:
        print(f"[{start}–{end}] {role}: {text}")
    print("\nBackend and delivery evidence (local milliseconds since attach):")
    for seq, _, elapsed, kind, data in rows:
        if kind.startswith(("session.input_", "session.output_")):
            continue
        print(f"#{seq} +{elapsed}ms {kind}: {json.dumps(data, ensure_ascii=False)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    report(parser.parse_args().trace)
