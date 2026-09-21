# Read-only chat policy

`chat.send` accepts the negotiated request policy
`mutation_policy="read_only", policy_version=1`. Clients must first read
`system.capabilities.chat_read_only_policy`; a client that requires version 1
must refuse an older engine instead of falling back to an empty tool allowlist.

The policy is an origin property for the whole turn. The engine checks explicit
and semantic slash-command effects before routing, does not acknowledge
notifications or enqueue automatic sync work, and carries the policy through
task mode and executor threads. Mutating tools are refused again at the
assistant and task-executor boundaries, even if that conversation previously
received a session approval. Missing mutation authority fails closed on write
paths. Existing interactive calls that omit the policy keep their approval
workflow.

Read operations remain available, including help and memory/email searches.
The policy refuses memory store/update/delete/reset, agent processing, job
resume, update/hard-reset, task changes, sends/drafts, sync and other registered
write effects before their handler or tool runs. Explicit mutation requests are
refused before model dispatch and create no blob, rule, index, checkpoint, job
or LLM reservation. If a read-looking prompt reaches the chat model and the
model later proposes a mutation, the tool is still refused before approval or
execution; the already-completed chat inference remains ordinary paid work.

The `cs-kernel` `cs ask` client negotiates and sends this policy. Supervised
`cs chat` and draft composition keep their existing write-capable contracts.
