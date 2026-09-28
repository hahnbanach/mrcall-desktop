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
    print("PRIVATE CALL DIAGNOSTIC — handset playback requires caller confirmation")
    if not rows:
        print("Empty trace; incomplete evidence")
        return
    print("Call:", rows[0][4]["call_id"], "Config:", rows[0][4]["config_revision"])
    print("Attached UTC:", rows[0][1])
    print("Events:", len(rows), "Trace closed:", rows[-1][3] == "trace_closed")
    print("\nTranscript (delivery order; provider timeline in milliseconds):")
    role, text, start, end = None, "", None, None
    for _, _, _, kind, data in rows:
        if kind not in ("session.input_transcript.delta", "session.output_transcript.delta"):
            continue
        current = "caller" if kind == "session.input_transcript.delta" else "voice"
        if role != current:
            if role:
                print(f"[{start}–{end}] {role}: {text}")
            role, text, start = current, "", data.get("start_ms")
        text += data.get("delta") or ""
        end = data.get("end_ms")
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
