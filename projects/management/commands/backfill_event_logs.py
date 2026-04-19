from __future__ import annotations

import djclick as click

from projects.event_logs import backfill_event_logs


@click.command()
@click.option("--dry-run", is_flag=True, help="Show how many missing creation events would be inserted.")
def command(dry_run: bool) -> None:
    """Backfill missing creation events for existing projects, features, and tasks."""
    result = backfill_event_logs(dry_run=dry_run)
    action = "Would create" if dry_run else "Created"
    click.echo(
        f"{action} {result.created_count} event logs; skipped {result.skipped_count} entities with existing logs.",
    )
