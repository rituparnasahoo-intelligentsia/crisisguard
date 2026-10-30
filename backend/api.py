"""CrisisGuard AI - Person C's API layer (FastAPI + SSE), wired to the real backend.

Run from the REPO ROOT:  uvicorn backend.api:app --reload --port 8000
Docs: http://localhost:8000/docs

Flow:
  POST /incidents            -> saves incident, runs Person A's orchestrator in a worker thread,
                                streams progress on /events
  POST /proposals/{id}/approve -> re-validates, reserves every resource in ONE transaction
  POST /proposals/{id}/reject  -> commander rejects
"""
import asyncio
import dataclasses
import json
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend import database, hospital_state
from backend.schemas import (EmergencyReport, ReservationResult, ResourceBundle,
                             ResourceItem)
from backend.validator import validate_bundle

DISCLAIMER = "Simulated resource logistics only; not clinical advice"

app = FastAPI(title="CrisisGuard AI")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

subscribers: set[asyncio.Queue] = set()
runs: dict[str, dict] = {}            # incident_id -> latest pipeline summary (for the UI)
model_status = {"available": True, "message": ""}
_orchestrator = None                   # created lazily so a missing API key doesn't crash startup


# ----------------------------------------------------------------- helpers
def _plain(obj):
    """Turn pydantic models / dataclasses / rows into JSON-safe data."""
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump()
    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        obj = dataclasses.asdict(obj)
    return jsonable_encoder(obj)


def publish(event: str, data: dict):
    """Push one event to every open SSE client (must run on the event-loop thread)."""
    for q in list(subscribers):
        q.put_nowait({"event": event, "data": _plain(data)})


def _get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        from backend.orchestrator import Orchestrator
        _orchestrator = Orchestrator()
    return _orchestrator


def _snapshot(conn, hospital_id: str) -> dict:
    """Live hospital state handed to the planner. Rows include state_version."""
    return {
        "hospital_id": hospital_id,
        "beds": hospital_state.get_available_beds(conn, hospital_id),
        "doctors": database.list_doctors(conn, hospital_id, available_only=True),
        "nurses": database.list_available_nurses(conn),
        "equipment": database.list_equipment_units(conn, hospital_id, status="available"),
    }


# ----------------------------------------------------------------- pipeline (worker thread)
def _run_pipeline(report: EmergencyReport, loop: asyncio.AbstractEventLoop):
    def emit(event, data):
        loop.call_soon_threadsafe(publish, event, data)

    emit("pipeline_started", {"incident_id": report.incident_id})
    attempt = {"n": 0}
    try:
        with database.get_connection() as conn:
            hs = _snapshot(conn, report.hospital_id)

            def validator(bundle: ResourceBundle):
                attempt["n"] += 1
                res = validate_bundle(conn, bundle)
                emit("plan_valid" if res.valid else "validation_failed",
                     {"incident_id": report.incident_id, "attempt": attempt["n"],
                      "bundle": bundle, "validation": res})
                return res

            result = _get_orchestrator().run(
                report.description, hs,
                incident_id=report.incident_id, patient_id=report.patient_id,
                validator_func=validator)

            summary = {
                "incident_id": report.incident_id,
                "facts": _plain(result.facts) if result.facts else None,
                "summary": result.summary,
                "attempts": result.attempts,
                "errors": result.errors,
                "escalated": result.escalated,
                "confidence": result.overall_confidence,
                "human_help_probability": result.human_help_probability,
                "uncertainty_note": result.uncertainty_note,
                "disclaimer": DISCLAIMER,
                "proposal_id": None,
                "bundle": None,
            }
            emit("facts_extracted", {"incident_id": report.incident_id,
                                     "facts": summary["facts"],
                                     "confidence": result.overall_confidence})

            if result.escalated or result.bundle is None:
                database.add_audit_event(conn, "escalated", None, {
                    "incident_id": report.incident_id, "errors": result.errors})
                emit("escalated", summary)
            else:
                b = result.bundle
                with conn.transaction():
                    database.save_bundle_proposal(
                        conn, proposal_id=b.proposal_id, incident_id=b.incident_id,
                        patient_id=b.patient_id, explanation=b.explanation,
                        input_snapshot=_plain(hs), valid=True,
                        reason=result.validation.reason if result.validation else "",
                        status="pending_review")
                    for it in b.items:
                        database.add_proposal_item(conn, b.proposal_id, it.resource_type,
                                                   it.resource_id, it.state_version)
                    database.add_audit_event(conn, "bundle_proposed", b.proposal_id,
                                             {"items": len(b.items)})
                summary["proposal_id"] = b.proposal_id
                summary["bundle"] = _plain(b)
                emit("plan_ready", summary)
            runs[report.incident_id] = summary
            model_status.update(available=True, message="")
    except Exception as exc:                      # model down, DB down, bad output...
        model_status.update(available=False, message=str(exc))
        emit("model_down", {"incident_id": report.incident_id, "error": str(exc)})


# ----------------------------------------------------------------- routes
@app.get("/health")
def health():
    return {"status": "ok", "model_available": model_status["available"],
            "model_message": model_status["message"], "disclaimer": DISCLAIMER}


@app.get("/state")
def state(hospital_id: Optional[str] = None):
    with database.get_connection() as conn:
        return {
            "beds": database.list_beds(conn, hospital_id),
            "doctors": database.list_doctors(conn, hospital_id),
            "nurses": database.list_nurses(conn),
            "equipment": database.list_equipment_units(conn, hospital_id),
        }


@app.post("/incidents")
async def create_incident(report: EmergencyReport):
    with database.get_connection() as conn:
        if database.get_incident(conn, report.incident_id):
            raise HTTPException(409, "incident_id already exists")
        database.save_incident(conn, report)   # <-- Person B must add this (see notes)
        database.add_audit_event(conn, "incident_created", None,
                                 {"incident_id": report.incident_id})
    asyncio.create_task(asyncio.to_thread(_run_pipeline, report, asyncio.get_running_loop()))
    return {"incident_id": report.incident_id, "status": "processing"}


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str):
    if incident_id not in runs:
        raise HTTPException(404, "No finished run yet for this incident")
    return runs[incident_id]


class Decision(BaseModel):
    reviewer: str = "commander"
    reason: str = ""


def _load_pending(conn, proposal_id: str) -> dict:
    prop = database.get_proposal(conn, proposal_id)
    if not prop:
        raise HTTPException(404, "Unknown proposal_id")
    if prop["status"] != "pending_review":
        raise HTTPException(409, f"Proposal is already '{prop['status']}'")
    return prop


class _Stale(Exception):
    pass


@app.post("/proposals/{proposal_id}/approve", response_model=ReservationResult)
async def approve(proposal_id: str, d: Decision = Decision()):
    def work() -> ReservationResult:
        with database.get_connection() as conn:
            prop = _load_pending(conn, proposal_id)
            items = database.list_proposal_items(conn, proposal_id)
            bundle = ResourceBundle(
                proposal_id=proposal_id, patient_id=prop["patient_id"],
                incident_id=prop["incident_id"], explanation=prop["explanation"] or "",
                items=[ResourceItem(resource_type=i["resource_type"],
                                    resource_id=i["resource_id"],
                                    state_version=i["version_used"]) for i in items])

            # Step 8 of the architecture: re-check against CURRENT state at approval time
            check = validate_bundle(conn, bundle)
            if not check.valid:
                stale = any("stale" in e or "changed" in e for e in check.errors)
                outcome = "stale" if stale else "rejected"
                database.add_audit_event(conn, f"approval_{outcome}", proposal_id,
                                         {"errors": check.errors})
                return ReservationResult(outcome=outcome, reason="; ".join(check.errors))

            incident = database.get_incident(conn, bundle.incident_id)
            hid = incident["hospital_id"]
            try:
                with conn.transaction():          # all-or-nothing
                    for it in bundle.items:
                        if it.resource_type == "bed":
                            ok = database.mark_bed_reserved(conn, it.resource_id, it.state_version)
                        elif it.resource_type == "equipment":
                            ok = database.mark_equipment_reserved(conn, it.resource_id, it.state_version)
                        elif it.resource_type == "nurse":
                            ok = database.mark_nurse_assigned(conn, it.resource_id, it.state_version)
                        else:  # doctor
                            ok = database.touch_doctor_version(conn, it.resource_id, it.state_version)
                        if ok is None:
                            raise _Stale(f"{it.resource_type} {it.resource_id} changed")
                    alloc = database.create_allocation(
                        conn, hospital_id=hid, incident_id=bundle.incident_id,
                        patient_id=bundle.patient_id, proposal_id=proposal_id)
                    adders = {"bed": database.add_allocation_item_bed,
                              "doctor": database.add_allocation_item_doctor,
                              "nurse": database.add_allocation_item_nurse,
                              "equipment": database.add_allocation_item_equipment}
                    for it in bundle.items:
                        adders[it.resource_type](conn, alloc, hid, it.resource_id)
                    database.set_proposal_status(conn, proposal_id, "committed")
                    database.record_approval(conn, proposal_id, d.reviewer, "approved", d.reason)
                    database.add_audit_event(conn, "approved_committed", proposal_id,
                                             {"allocation_id": alloc, "reviewer": d.reviewer})
            except _Stale as e:
                database.add_audit_event(conn, "approval_stale", proposal_id, {"reason": str(e)})
                return ReservationResult(outcome="stale", reason=str(e))
            return ReservationResult(allocation_id=alloc, outcome="committed",
                                     reason="Plan approved and resources reserved")

    res = await asyncio.to_thread(work)
    publish(res.outcome, {"proposal_id": proposal_id, **res.model_dump()})
    return res


@app.post("/proposals/{proposal_id}/reject", response_model=ReservationResult)
async def reject(proposal_id: str, d: Decision = Decision()):
    def work():
        with database.get_connection() as conn:
            _load_pending(conn, proposal_id)
            with conn.transaction():
                database.set_proposal_status(conn, proposal_id, "rejected_by_reviewer")
                database.record_approval(conn, proposal_id, d.reviewer, "rejected", d.reason)
                database.add_audit_event(conn, "rejected_by_reviewer", proposal_id,
                                         {"reviewer": d.reviewer})
    await asyncio.to_thread(work)
    res = ReservationResult(outcome="rejected", reason=d.reason or "Rejected by commander")
    publish("rejected", {"proposal_id": proposal_id, **res.model_dump()})
    return res


@app.get("/audit")
def audit(proposal_id: Optional[str] = None):
    with database.get_connection() as conn:
        return jsonable_encoder(database.list_audit_events(conn, proposal_id))


@app.get("/events")
async def events():
    """Server-Sent Events: the dashboard listens here for live updates."""
    q: asyncio.Queue = asyncio.Queue()
    subscribers.add(q)

    async def stream():
        try:
            while True:
                item = await q.get()
                yield {"event": item["event"], "data": json.dumps(item["data"])}
        finally:
            subscribers.discard(q)

    return EventSourceResponse(stream())


import os
from fastapi.staticfiles import StaticFiles
if os.path.isdir("frontend_dist"):
    app.mount("/", StaticFiles(directory="frontend_dist", html=True), name="web")