"""The company-memory commands of the ``zylch`` CLI.

``memory-status``, ``memory-sweep``, ``memory-join`` and ``memory-reviews``, each
booting the profile the way every subcommand of ``zylch.cli.main`` does, which
registers them on its group (:data:`MEMORY_COMMANDS`). The profile helpers are
read from ``zylch.cli.main`` when a command runs, never at import, because that
module imports this one.
"""

import logging

import click

logger = logging.getLogger(__name__)


@click.command(name="memory-status")
@click.pass_context
def memory_status(ctx):
    """Show this profile's company memory: key, availability, size, contributors."""
    from zylch.cli import main as _main

    _main._configure_logging()
    profile_name = ctx.obj.get("profile") if ctx.obj else None
    profile = _main._setup_profile(profile_name, lock=False)
    logger.info(f"[CLI] memory-status profile={profile}")
    from zylch.memory.company_key import current_company_key
    from zylch.memory.join import status
    from zylch.storage.storage import Storage

    Storage.get_instance()  # boots: migrations, store attach
    out = status()
    click.echo(f"profile:      {profile}")
    click.echo(f"memory key:   {current_company_key() or '(none)'}")
    note = out.get("reason") or out.get("joining_reason")
    click.echo(f"available:    {out['available']}" + (f"  ({note})" if note else ""))
    if out.get("available"):
        click.echo(f"self-notion:  {out.get('self_notion') or '(unset)'}")
        click.echo(
            f"entries:      {out.get('blob_count', 0)} blobs, {out.get('fact_count', 0)} facts"
        )
        click.echo(f"contributors: {', '.join(out.get('contributors') or []) or '(none yet)'}")


@click.command(name="memory-sweep")
@click.pass_context
def memory_sweep(ctx):
    """Consolidate this company's memory now: retention, then duplicate entities.

    Same operation the desktop Settings Maintenance card runs and the daemon
    runs after each update, inside one bounded preparation run like theirs (a
    paused or running preparation answers skipped); once per company (another
    engine holding the lock makes this a no-op that says so). Pairs need an
    LLM: BYOK key in the profile, or a live MrCall session — a credits profile
    with no session answers no_llm after retention and exits 2, as it does when
    the company memory or its journal cannot answer.
    """
    import asyncio

    from zylch.cli import main as _main

    _main._configure_logging()
    profile_name = ctx.obj.get("profile") if ctx.obj else None
    profile = _main._setup_profile(profile_name, lock=False)
    logger.info(f"[CLI] memory-sweep profile={profile}")
    from zylch.cli.utils import get_owner_id
    from zylch.memory.consolidation import consolidate, failed, summary_lines
    from zylch.services.preparation import PreparationStopped, preparation_run
    from zylch.storage.storage import Storage

    Storage.get_instance()
    owner = get_owner_id()
    try:
        with preparation_run(owner):
            summary = asyncio.run(consolidate(owner, force=True))
    except PreparationStopped as exc:
        click.echo(f"skipped: {exc}")
        return
    for line in summary_lines(summary):
        click.echo(line)
    if summary.get("no_llm") or failed(summary):
        raise SystemExit(2)


@click.command(name="memory-join")
@click.argument("key", required=False)
@click.option("--yes", is_flag=True, help="Join without the confirmation prompt (scripts).")
@click.option(
    "--drain",
    is_flag=True,
    help="First run one memory pass of this profile, admitted by preparation (it may pay).",
)
@click.option(
    "--release-fence",
    "release",
    is_flag=True,
    help="Release a join fence left on this company memory by a join that stopped.",
)
@click.pass_context
def memory_join(ctx, key, yes, drain, release):
    """Join the company memory KEY names: preview (the echo), confirm, merge, switch.

    The same gesture the desktop Settings card performs, for a headless
    profile on the host. Needs the profile lock: stop its daemon first
    (scripts/server/join-company.sh does stop, join, start). A join is refused
    while this profile's memory work in its current company is unsettled; the
    refusal lists each blocking operation with the command that settles it.
    ``--drain`` first runs one ordinary memory pass under preparation, which
    resumes pending work and lands settled sources' checkpoints; a paused or
    busy preparation refuses it. ``--release-fence`` (no KEY) releases a join
    fence still in phase ``fenced`` on the bound company; an accepted one is
    finished only by its own profile's recovery.
    """
    from zylch.cli import main as _main

    _main._configure_logging()
    profile_name = ctx.obj.get("profile") if ctx.obj else None
    profile = _main._setup_profile(profile_name, lock=True)
    logger.info(f"[CLI] memory-join profile={profile} drain={drain} release_fence={release}")
    from zylch.memory.company_key import current_company_key
    from zylch.memory.join import join, preview, release_fence
    from zylch.storage.storage import Storage

    Storage.get_instance()
    if release:
        out = release_fence()
        click.echo("released the join fence" if out.get("ok") else f"refused: {out.get('reason')}")
        if not out.get("ok"):
            raise SystemExit(2)
        return
    if not key:
        click.echo("refused: give the KEY of the company memory to join")
        raise SystemExit(2)
    echo = preview(key)
    if not echo.get("well_formed"):
        click.echo(f"refused: {echo.get('reason')}")
        raise SystemExit(2)
    if not echo.get("exists"):
        click.echo("refused: no company memory exists for this key on this host")
        raise SystemExit(2)
    if current_company_key() == key.strip():
        click.echo("already on this memory key")
    click.echo(
        f"joining: {echo.get('self_notion') or '(self-notion unset)'} · "
        f"{echo.get('blob_count', 0)} entries · contributors: "
        f"{', '.join(echo.get('contributors') or []) or '(none)'}"
    )
    if not yes and not click.confirm(
        "Merge this profile's memory into it and switch?", default=False
    ):
        click.echo("aborted")
        raise SystemExit(1)
    out = join(key, drain=drain)
    if not out.get("ok"):
        click.echo(f"refused: {out.get('reason')}")
        for row in out.get("blocking") or []:
            click.echo(f"  {row['event_id']}  {row['state']}  {row['source_ref']}")
            click.echo(f"    settle with: {row['verb']}")
        raise SystemExit(2)
    merged = out.get("merged") or {}
    click.echo(
        f"joined: merged {merged.get('blobs', 0)} entries"
        + (
            f", {merged['facts_converged']} fact(s) converged"
            if merged.get("facts_converged")
            else ""
        )
        + f"; now {out.get('blob_count', 0)} entries, contributors: {', '.join(out.get('contributors') or [])}"
    )


@click.command(name="memory-reviews")
@click.option("--retry", "retry_id", default=None, help="Decide this parked operation again.")
@click.option("--dismiss", "dismiss_id", default=None, help="Settle this operation as skipped.")
@click.pass_context
def memory_reviews(ctx, retry_id, dismiss_id):
    """List this profile's unsettled memory operations, or resolve one.

    Without an option: every operation of this profile's account in the bound
    company memory that is in review, failed or pending, with the actions each
    admits. ``--dismiss <id>`` settles one as skipped (a child's source then
    lands on the next run, unpaid); ``--retry <id>`` reopens a review the next
    run can decide again. A refusal prints its reason and exits 2.
    """
    from zylch.cli import main as _main

    _main._configure_logging()
    profile_name = ctx.obj.get("profile") if ctx.obj else None
    profile = _main._setup_profile(profile_name, lock=False)
    logger.info(f"[CLI] memory-reviews profile={profile}")
    from zylch.memory.company_key import current_company_key
    from zylch.memory.mnemonic.reviews import (
        DISMISS,
        RETRY,
        ReviewRefused,
        list_unsettled,
        resolve,
    )
    from zylch.memory.mnemonic.session import JournalError
    from zylch.storage.storage import Storage

    if retry_id and dismiss_id:
        click.echo("refused: give one of --retry and --dismiss")
        raise SystemExit(2)
    Storage.get_instance()
    try:
        if retry_id or dismiss_id:
            out = resolve(retry_id or dismiss_id, RETRY if retry_id else DISMISS)
            parent = out.get("parent")
            click.echo(
                f"{out['action']}: {out['event_id']} is now {out['state']}"
                + (f"; parent {parent['event_id']} is {parent['state']}" if parent else "")
            )
            return
        rows = list_unsettled(current_company_key() or "")
    except (ReviewRefused, JournalError) as exc:
        click.echo(f"refused: {exc}")
        raise SystemExit(2)
    if not rows:
        click.echo("no unsettled memory operations")
        return
    for row in rows:
        click.echo(
            f"{row['event_id']}  {row['state']}  {row['source_ref']}"
            + (f"  parent={row['parent_event_id']}" if row["parent_event_id"] else "")
            + f"  actions={','.join(row['actions'])}"
            + (f"  restrictions={len(row['restrictions'])}" if row["restrictions"] else "")
        )
        if row["reason"]:
            click.echo(f"    reason: {row['reason']}")


MEMORY_COMMANDS = (memory_status, memory_sweep, memory_join, memory_reviews)
