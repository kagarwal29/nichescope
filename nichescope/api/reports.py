"""Public channel report endpoint — no auth required."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from nichescope.models import get_db
from nichescope.services.report_generator import generate_channel_report

router = APIRouter(prefix="/api/report", tags=["reports"])


@router.get("/{channel_id}")
async def public_channel_report(
    channel_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint: generate a report for any YouTube channel.

    This is the viral growth hook — shareable URL like:
    nichescope.com/report/UC... or nichescope.com/report/@handle

    No authentication required.
    """
    report = await generate_channel_report(db, channel_id)

    if not report:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Channel '{channel_id}' not found in our database. "
                "We need to ingest it first — try adding it as a competitor in your niche."
            ),
        )

    return report.to_dict()
