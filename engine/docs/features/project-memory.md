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
