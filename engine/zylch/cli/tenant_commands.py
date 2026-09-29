"""Host-side tenant commands of the ``zylch`` CLI (plan M2 of
docs/execution-plans/2026-09-29-toward-sandbox.md).

``rekey``, ``memory-relocate-store`` and ``memory-offboard`` are run by the
operator (through ``tenant-helper.sh`` / the runbook) while the profile's
daemon is stopped; ``memory-names`` is read-only. Registered on the
``zylch`` group like the memory commands.
"""

import logging

import click

logger = logging.getLogger(__name__)


def _read_key_file(path: str) -> str:
    """A Fernet key from a file (never from argv, which `ps` shows)."""
    with open(path, encoding="utf-8") as f:
        key = f.read().strip()
    if key.startswith("ENCRYPTION_KEY="):
        key = key[len("ENCRYPTION_KEY=") :].strip().strip('"')
    if not key:
        raise click.ClickException(f"empty key file: {path}")
    return key


@click.command(name="memory-names")
@click.pass_context
def memory_names(ctx):
    """Print the derived host names for this profile: Unix user, company
    group, store path (legacy and derived). Never the key itself."""
    from zylch.cli import main as _main
    from zylch.memory.company_key import current_company_key
    from zylch.memory.store import derived_memory_db_path, legacy_memory_db_path, memory_db_path
    from zylch.memory.tenant_names import company_group, unix_user
    import os

    _main._configure_logging()
    profile_name = ctx.obj.get("profile") if ctx.obj else None
    profile = _main._setup_profile(profile_name, lock=False)
    uid = os.environ.get("OWNER_ID", "") or profile
    click.echo(f"profile:       {profile}")
    click.echo(f"unix user:     {unix_user(uid)}")
    key = current_company_key()
    if not key:
        click.echo("company group: (no MEMORY_KEY)")
        return
    click.echo(f"company group: {company_group(key)}")
    click.echo(f"store (now):   {memory_db_path(key)}")
    click.echo(f"store legacy:  {legacy_memory_db_path(key)}")
    click.echo(f"store derived: {derived_memory_db_path(key)}")


@click.command(name="memory-relocate-store")
@click.pass_context
def memory_relocate_store(ctx):
    """2a: move this company's store from `<key>.db` to its derived name.
    Every daemon of the company must be stopped first. Idempotent."""
    from zylch.cli import main as _main
    from zylch.memory.company_key import current_company_key
    from zylch.memory.store import MemoryUnavailable, relocate_store

    _main._configure_logging()
    profile_name = ctx.obj.get("profile") if ctx.obj else None
    profile = _main._setup_profile(profile_name, lock=True)
    key = current_company_key()
    if not key:
        click.echo("refused: this profile has no MEMORY_KEY")
        raise SystemExit(2)
    logger.info(f"[CLI] memory-relocate-store profile={profile}")
    try:
        moved = relocate_store(key)
    except MemoryUnavailable as e:
        click.echo(f"refused: {e.reason}")
        raise SystemExit(2) from None
    click.echo(f"relocated to {moved}" if moved else "nothing to move (already derived or absent)")


@click.command(name="rekey")
@click.option("--from-key-file", "from_file", required=True, help="File holding the current key.")
@click.option("--to-key-file", "to_file", required=True, help="File holding the new key.")
@click.option("--verify", is_flag=True, help="After rewriting, prove every row decrypts under the new key.")
@click.option("--verify-only", is_flag=True, help="Only verify under --to-key-file; write nothing.")
@click.pass_context
def rekey(ctx, from_file, to_file, verify, verify_only):
    """Re-encrypt this profile's stored credentials from one key to another.

    Idempotent (rows already under the new key are left alone), handles the
    nested `encrypted:` fields, encrypts plaintext rows. Swap the two files
    to roll back. Run while the daemon is stopped."""
    from zylch.cli import main as _main
    from zylch.storage import rekey as rk

    _main._configure_logging()
    profile_name = ctx.obj.get("profile") if ctx.obj else None
    profile = _main._setup_profile(profile_name, lock=True)
    logger.info(f"[CLI] rekey profile={profile} verify={verify} verify_only={verify_only}")
    new_key = _read_key_file(to_file)
    if not verify_only:
        report = rk.rekey(_read_key_file(from_file), new_key)
        click.echo(
            f"rewritten: {report.rewritten}  already under new key: {report.already}"
            f"  plaintext encrypted: {report.plaintext}  failed: {len(report.failed)}"
        )
        for line in report.failed:
            click.echo(f"  FAILED {line}")
        if not report.ok:
            raise SystemExit(2)
    if verify or verify_only:
        check = rk.verify(new_key)
        click.echo(f"verify: {check.rewritten} row(s) decrypt under the new key, {len(check.failed)} do not")
        for line in check.failed:
            click.echo(f"  FAILED {line}")
        if not check.ok:
            raise SystemExit(2)


@click.command(name="memory-offboard")
@click.option("--yes", is_flag=True, help="Delete without the confirmation prompt (scripts).")
@click.option(
    "--last-holder",
    is_flag=True,
    help="This profile is its company's last key holder: delete the whole store file too.",
)
@click.pass_context
def memory_offboard(ctx, yes, last_holder):
    """Remove this profile from its company memory before the profile is deleted.

    Deletes only this profile's owned rule rows (`template:`/`prefs:`);
    company-family rows stay with the company, provenance included. With
    --last-holder (the helper decides that from group membership) the store
    file is deleted as well. Run as the profile's user, daemon stopped."""
    from zylch.cli import main as _main

    _main._configure_logging()
    profile_name = ctx.obj.get("profile") if ctx.obj else None
    profile = _main._setup_profile(profile_name, lock=True)
    logger.info(f"[CLI] memory-offboard profile={profile} last_holder={last_holder}")
    from zylch.cli.utils import get_owner_id
    from zylch.memory.company_key import current_company_key
    from zylch.memory.offboard import delete_owned_rules, delete_store
    from zylch.storage.storage import Storage

    key = current_company_key()
    if not key:
        click.echo("nothing to do: this profile has no MEMORY_KEY")
        return
    Storage.get_instance()
    owner = get_owner_id()
    if not yes and not click.confirm(
        f"Delete {owner}'s own rule rows from the company memory"
        + (" AND the whole store file" if last_holder else "")
        + "?",
        default=False,
    ):
        click.echo("aborted")
        raise SystemExit(1)
    removed = delete_owned_rules(owner)
    click.echo(f"removed {removed} owned rule row(s)")
    if last_holder:
        path = delete_store(key)
        click.echo(f"deleted store {path}" if path else "no store file to delete")


TENANT_COMMANDS = (memory_names, memory_relocate_store, rekey, memory_offboard)
