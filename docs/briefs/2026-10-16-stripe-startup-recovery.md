# Stripe Settings startup recovery

## Intent

The installed Stripe test candidate leaves the key input disabled with company
and host shown as Checking. The selected remote engine is healthy and reports
an authenticated owner, available memory, and disconnected Stripe status.

## Scope and constraints

Repair the Stripe card startup and recovery UI in the isolated test branch.
Keep identity, company, transport and generation fences. Do not restart or
change the remote engine: it is frozen for another operator's acceptance case.
Do not change shared Qonto behavior or publish a stable release.

## Acceptance

Startup verifies or repairs the engine session, handles cached ready events and
reconnects safely, and has a bounded visible loading state. Failure or unavailable
memory displays a specific blocked state with usable retry. Old requests cannot
enable the input after context changes. Tests exercise these startup cases with
the real card and preload. Produce a signed/notarized replacement test installer.
Real installed-user and restricted-key acceptance remains pending until observed.
