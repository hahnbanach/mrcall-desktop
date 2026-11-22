# Identify mailboxes rejected by assignment membership checks

An assignment read can fail before opening a mailbox. The membership check examines every active mailbox on the actor's profile. Its generic exception loses the identity of each rejected mailbox. The message being inspected can belong to a different, verified mailbox.

For this refusal, the unit journal must identify every offending profile mailbox unambiguously. The existing private engine diagnostic reader must expose the binding failure on the same request trace with a stable reference for each mailbox. An operator with access to the profile must be able to resolve each reference using its mailbox inventory. Record no mail content, credential, raw exception text or unmasked address. The engine owns the evidence because it has both the authenticated actor and the mailbox inventory.

Preserve all holds, failure reasons, exit semantics and the existing projection and inventory schemas. Attribute only a proven membership mismatch. A missing inventory, a profile failure or a provider failure is a different diagnostic. Use synthetic mailbox fixtures to verify a different conversation mailbox, multiple offenders, clean bindings and independent requests. Work is confined to the source branch. Installation and trust changes are separate operations.
