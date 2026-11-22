# Assignment projections with several members' mailboxes in one profile

A scheduled read on the hosted engine returned `SOURCE_UNAVAILABLE` for a
conversation in the authenticated member's verified mailbox. Its trace rejected
two unrelated active mailbox rows. Both addresses belong to other verified
members of the same company. The tick held the conversation on an error and
could not finish its assignment reads.

An assignment projection must evaluate the member's own mail with the same
evidence it would require if only that member's mailboxes were connected.
A connected mailbox belonging to another verified member gives the actor no
authority over it. Its mere presence must not disable a verified conversation.
Keep a thread held when its evidence depends on an excluded, missing or
ambiguous mailbox. Preserve the distinct human hold when a verified member
wrote last. Keep unknown bindings, stale authority, and conflicting ancestry
fail-closed. Do not establish absence of a reply from an incomplete scan of
the actor's own mailboxes.

Acceptance uses the real projection entry point and synthetic mail. Cover
a last member reply, an ordinary eligible thread, and a thread spanning
mailbox boundaries. Demonstrate that an excluded provider is never opened,
that all verified actor mailboxes still participate in complete scans, and
that direct assignment mutations and complete closure proofs keep their
existing admission. Preserve diagnostics for actual refusals.

The engine owns this correction. Trust files, store contents, clone schedules,
kernel releases and customer mail are outside the change. Production rollout
requires separate release authority.
