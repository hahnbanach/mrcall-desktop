# Written project memory

<!-- doc-scope:start -->
Scope: engine storage and RPC contracts for authored company project documents;
separate from generated entity blobs and their deduplication.
<!-- doc-scope:end -->

The shared company memory SQLite file owns `project_space`,
`project_documents`, and `project_revisions`. Profiles holding the same company
memory capability see the same documents. Author UID records provenance only.
Documents do not enter blob extraction or automatic deduplication.

A store has an opaque UUID `space_id`, unrelated to its capability. Every
successful project RPC returns it; create/write requires it. Company joins retain
the destination UUID, so an old working copy cannot write into a newly joined
company. Each operation captures the currently bound store and runs its metadata
and content queries in one transaction.

Documents are keyed by lowercase ASCII project slug and relative path. Raw bytes,
SHA-256, length, timestamp and author UID are retained in immutable revisions.
Revisions increase from one. Writes take the SQLite writer lock before comparing
the expected revision; zero creates only. Identical-byte retries return the
existing revision. Divergent stale writes refuse without overwriting anything.
There is no deletion RPC.

| RPC | Parameters | Result |
| --- | --- | --- |
| `projects.list` | `limit?`, `offset?` | Project summaries (`project`, `file_count`) |
| `projects.files` | `project`, `limit?`, `offset?` | Current document metadata |
| `projects.read` | `project`, `path`, `revision?` | Metadata and `content_base64` |
| `projects.write` | `space_id`, `project`, `path`, `content_base64`, `expected_revision` | Current document metadata |
| `projects.history` | `project`, `path`, `limit?`, `offset?` | Revision metadata, newest first |
| `projects.create` | `space_id`, `project`, `files` | `{space_id, project, files: [metadata]}` |

`files` in create is an object mapping paths to base64 strings; creation is atomic
and refuses existing projects. All list responses have `space_id`, `items`,
`total`, `limit`, `offset`. Metadata contains `project`, `path`, `revision`,
`sha256`, `size`, `author_uid`, `created_at`. Missing project files/history return
not-found; use `projects.list` to discover the current company space.

Limits: pages default to 50 and permit at most 100 items; each file permits 4 MiB
raw; create permits 1–16 files and at most 1 MiB aggregate. Paths permit at most
512 UTF-8 bytes, with no absolute paths, traversal, empty segments, backslashes,
colons or control characters. Slugs match `[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?`. RPC operates
on bytes, not server filesystem paths. Clients must additionally reject symlinks
when importing/exporting local trees.

Application errors: `-32040` revision/project/history conflict, `-32041` wrong
company space, `-32044` missing document/project/revision, `-32043` unavailable
company memory. Invalid input is `-32602`. Write/create payloads are redacted from
RPC logging; unexpected project errors return a generic message without SQL or
payload details.

Company join preflights every document collision inside the destination write
transaction before copying blobs. Compatible history prefixes converge and all
additional revisions survive. Compatibility includes bytes, hashes, timestamps
and author provenance, not only equal current content. Divergent histories refuse
without changing membership or copying data. A source predating these tables
contributes no written documents. The existing destination UUID survives.

## Standing operator instructions (reserved project `operator-instructions`)

The operator's standing instructions are authored as files in the company's
`<company>-cs` clone, compiled there, and stored here as documents of the
reserved project `operator-instructions`. The engine owns this contract; the
kernel mirrors it as constants.

| Path | Scope | Injected where |
| --- | --- | --- |
| `procedures.md` | one per company | every profile bound to the company memory |
| `mail/<mailbox>.md` | one per mailbox; `<mailbox>` is the profile `EMAIL_ADDRESS` lower-cased, verbatim | only the profile whose address matches |
| `phone.md` | one per company | the telephone company-notes source (`services/voice/company_notes.py`) |

Prompt injection (`get_personal_data_section`): `FRAMING + identity` when
only the mailbox document exists, `FRAMING + procedures` when only the
company document exists, `FRAMING + identity + "\n\n" + procedures` when
both; no block at all when neither exists. `FRAMING` is the constant in
`services/operator_instructions.py`. There is no other source of standing
instructions: no profile setting, no fallback.

| RPC | Parameters | Result |
| --- | --- | --- |
| `instructions.store` | `space_id`, `path`, `content_base64`, `expected_revision` | Document metadata (as `projects.write`) |
| `instructions.preview` | — | `{space_id, documents: [{path, revision, sha256, content_base64}], block}` for the calling profile; read-only, no LLM call |

`instructions.store` is the only writer: `projects.write` and
`projects.create` refuse the reserved slug with `-32046`. Authorisation is
derived from the profile's provenance, never from a setting: the profile
that minted the company memory (`MEMORY_KEY_SOURCE=mint`) may store any of
the three paths; any other profile may store only its own `mail/<mailbox>.md`
(`-32045` otherwise). Any other path is `-32602`. Store payloads are redacted
from RPC logging like project writes. Revisions are immutable and there is
no deletion: a wrong document is corrected by a new revision.
