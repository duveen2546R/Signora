from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR
from app.core.db import get_session
from app.ingest.rigprofile import RigProfileError, from_dict
from app.models import RigProfileRow

router = APIRouter(prefix="/rigs", tags=["rigs"])


@router.post("")
async def upload_rig_profile(file: UploadFile, session: Session = Depends(get_session)):
    raw = await file.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"not valid JSON: {exc}") from exc

    digest = hashlib.sha256(raw).hexdigest()[:16]
    try:
        rig = from_dict(data, digest=digest)
    except RigProfileError as exc:
        raise HTTPException(422, str(exc)) from exc

    existing = session.scalars(
        select(RigProfileRow).where(RigProfileRow.digest == digest)
    ).first()
    if existing is None:
        session.add(RigProfileRow(
            digest=digest, avatar_name=rig.avatar_name,
            hip_height=rig.hip_height, payload=data,
        ))
        session.commit()

    return {
        "digest": digest,
        "avatarName": rig.avatar_name,
        "hipHeight": rig.hip_height,
        "boneCount": len(rig.bones),
        "reused": existing is not None,
    }


@router.get("")
def list_rig_profiles(session: Session = Depends(get_session)):
    rows = session.scalars(
        select(RigProfileRow).order_by(RigProfileRow.created_at.desc())
    ).all()
    return [
        {"digest": r.digest, "avatarName": r.avatar_name,
         "hipHeight": r.hip_height, "createdAt": r.created_at}
        for r in rows
    ]


@router.get("/calibration")
def calibration_landmarks():
    """The avatar's own bind pose, as landmarks.

    The Unity runtime maps whatever pose it sees during calibration onto the avatar's bind
    rotation. Using the avatar's own bind pose makes that mapping an identity, so signs play at
    their true orientation instead of being offset by the difference between the performer's
    resting pose and the avatar's T-pose.

    Regenerate with `python tools/extract_bind_pose.py <avatar.glb>` if the avatar changes.
    """
    path = BASE_DIR / "data" / "calibration.json"
    if not path.exists():
        raise HTTPException(
            404,
            "no calibration pose has been generated; run "
            "tools/extract_bind_pose.py against the avatar's .glb",
        )
    return FileResponse(path, media_type="application/json")
