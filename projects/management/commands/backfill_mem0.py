from __future__ import annotations

import djclick as click

from projects.mem0_backfill import backfill_mem0


@click.command()
@click.option("--dry-run", is_flag=True, help="Show how many existing features and tasks would be synced to mem0.")
def command(dry_run: bool) -> None:
    """Backfill mem0 with existing project features and tasks."""
    result = backfill_mem0(dry_run=dry_run)
    action = "Would sync" if dry_run else "Synced"
    click.echo(
        f"{action} {result.synced_feature_count} features and {result.synced_task_count} tasks "
        f"to mem0 ({result.synced_count} total).",
    )
