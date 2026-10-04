"""Resumable publication events and authorized, current job progress over SSE."""
import asyncio
import json
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from . import db as database
from .db import Job, OutboxEvent
from .security import current_user, read_layer
from .store import state


def frame(event, value, identifier=None):
    prefix = f'id: {identifier}\n' if identifier is not None else ''
    return prefix+f'event: {event}\ndata: {json.dumps(value, ensure_ascii=False)}\n\n'


def job_progress(db, layer, user):
    """Expose no queue payloads or results through the public version stream."""
    if not user or user.role not in {'operator', 'admin', 'verifier'}:
        return []
    jobs = db.scalars(select(Job).where(Job.layer == layer).order_by(Job.created_at.desc()).limit(100))
    return [{'id': job.id, 'job_id': job.id, 'layer': job.layer, 'kind': job.kind,
             'status': job.status, 'progress': job.progress, 'attempts': job.attempts,
             'finished_at': job.finished_at, 'error': job.error} for job in jobs]


def event_response(request: Request, layer='fixture', after=0, once=False):
    try:
        cursor = max(after, int(request.headers.get('last-event-id', '0')))
        if cursor < 0:
            raise ValueError()
    except ValueError:
        raise HTTPException(422, 'Last-Event-ID musi być nieujemnym numerem publikacji.')
    with database.SessionLocal() as db:
        read_layer(db, request, layer)
        latest = db.scalar(select(func.max(OutboxEvent.id)).where(OutboxEvent.layer == layer)) or 0
        if not cursor:
            cursor = latest
        cursor = min(cursor, latest)

    async def stream():
        nonlocal cursor
        known_jobs, prior_user = {}, None
        for tick in range(30):
            if await request.is_disconnected():
                return
            with database.SessionLocal() as db:
                # Recheck the opaque session each time, including revocation and
                # expiry; an open connection does not extend an authorization.
                try:
                    user = read_layer(db, request, layer)
                except HTTPException:
                    return
                current_identity = (user.id, user.role) if user else None
                output = []
                if tick == 0:
                    output.append(frame('snapshot', {'layer': layer, **state(db, layer)}, cursor))
                if tick == 0 or current_identity != prior_user:
                    output.append(frame('session', {'authenticated': bool(user), 'role': user.role if user else None}))
                    known_jobs.clear()
                prior_user = current_identity
                rows = list(db.scalars(select(OutboxEvent).where(OutboxEvent.id > cursor, OutboxEvent.layer == layer).order_by(OutboxEvent.id).limit(100)))
                for row in rows:
                    cursor = row.id
                    output.append(frame('version', {'data_version': row.version, 'layer': row.layer}, row.id))
                for job in job_progress(db, layer, user):
                    if known_jobs.get(job['id']) != job:
                        output.append(frame('job', job))
                        known_jobs[job['id']] = job
            for item in output:
                yield item
            if once:
                return
            if not output:
                yield ': heartbeat\n\n'
            await asyncio.sleep(1)
    return StreamingResponse(stream(), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-store'})
