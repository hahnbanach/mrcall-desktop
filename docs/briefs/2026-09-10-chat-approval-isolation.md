# Isolate desktop chat approvals across clients

<!-- doc-scope:start -->
Scope: the existing engine chat session-approval collision between clients of
one profile; defines the problem and acceptance criteria without implementing
personal-account delegation or a general security review.
<!-- doc-scope:end -->

## Problem and evidence

Two desktop clients of the same remote profile use the same general-conversation
ID, `general` (`app/src/renderer/src/store/conversations.ts`). Engine
`engine/zylch/rpc/methods.py` stores `_session_auto_approvals` process-wide by
conversation ID and tool name. `chat_approve(mode="session")` adds a grant;
`_should_auto_approve` consults it without a client identity. No removal of that
grant appears in the module. Task-derived IDs can likewise recur across clients.

Consequently a session grant from client A can authorize the same tool in an
unrelated conversation on client B of that profile. The busy guard also uses
the shared conversation ID, so concurrent general turns can collide.

Confirmed through source review and isolated execution of the actual
`chat_approve` and `_should_auto_approve` functions on 2026-09-10. This was not a
live two-window test; no email was sent and no real account was used.

## Intended behavior

A session approval belongs to one explicitly identified conversation session.
It applies to subsequent turns in that session only, never to another client's
conversation just because it uses the same client-supplied label. One-shot
approvals and refusals keep their current meaning.

The engine must enforce the boundary; generating different IDs only in the
renderer is not sufficient. The implementation plan must select a server-owned
session or connection-scoped mechanism and specify its compatibility behavior.

For the existing desktop path, disconnection ends session grants. Reconnection
requires fresh approval. Clearing/closing a conversation must end its grants
without requiring a daemon restart. This deliberately chooses predictable
expiration over making a grant survive an ambiguous reconnect.

## Scope

- Bind pending approvals and reusable grants to their originating session.
- Prevent another session from answering an approval by presenting its tool ID.
- Isolate conversation busy state across clients while preserving serialization
  of turns within one conversation session.
- Make the desktop's “Allow for session” wording match its actual lifetime.
- Preserve the current safe disconnect handling for in-progress operations;
  grant cleanup must not cancel an irreversible send between remote execution
  and local recording.
- Preserve existing `once`/`deny` clients and cs-kernel's one-shot chat path.
  If a protocol addition is needed, define conservative behavior for old clients
  rather than silently allowing cross-client reuse.

Out: personal-user delegation, company roles, shared chat history, daemon job
resumption, a broad security review, or rebuilding desktop views. Implementation
timing is separate from the immediate configuration-to-clone product work.

## Acceptance criteria

1. With two real protocol clients on the same profile, A grants a harmless test
   tool for its session. A's next turn reuses it; B using the same conversation
   label still requires its own approval.
2. B cannot resolve A's pending approval even if it knows the tool-use ID.
3. Disconnect/reconnect and conversation clear/close invalidate grants; merely
   completing a turn in the same active session does not.
4. Two clients using `general` can work independently. A second concurrent turn
   inside one session retains the existing busy refusal.
5. One-shot approval, denial, edited input, cancelled turns, and legacy-client
   behavior remain covered through the dispatch/transport boundary.
6. No verification sends real mail. Use a harmless tool and exercise the actual
   approval flow rather than only assertions on an internal dictionary.

## Constraints and next gate

Keep ID tokens in memory and avoid logging capabilities. Scope all state to the
correct profile and session; do not widen authentication or reuse authority from
another profile. Document any additive IPC change in the existing contract.

Review this brief before planning implementation. Code, deployment, and a
general security audit are not requested by this document.
