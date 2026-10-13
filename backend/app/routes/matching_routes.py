"""Ranked recommendations and NGO accept / reject decisions."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import matching
from ..auth import get_current_user, require_roles
from ..database import get_db
from ..models import MatchRecommendation, User
from ..schemas import MatchOut, RejectRequest
from ..serializers import match_out
from ..services import accept_match, generate_matches, reject_match
from .donation_routes import get_visible_donation

router = APIRouter(prefix="/api/matches", tags=["matching"])


@router.get("/weights")
def weights():
    """The fixed weights and formulas used by the scoring engine (public)."""
    return {
        "weights": matching.WEIGHTS,
        "sum": round(sum(matching.WEIGHTS.values()), 6),
        "formulas": {
            "freshness": "F_i = 1 - min(T_i, 24) / 24",
            "proximity": "G_ij = exp(-D_ij / 5)",
            "capacity_fit": "C_ij = min(q_i, c_j) / max(q_i, c_j)",
            "demand_fit": "Q_ij = min(q_i, d_j) / max(q_i, d_j)",
            "priority": "P_j in [0, 1]",
            "score": "S_ij = wF*F + wG*G + wC*C + wQ*Q + wP*P",
        },
    }


@router.get("/donation/{donation_id}", response_model=list[MatchOut])
def recommendations_for_donation(donation_id: int, include_history: bool = False,
                                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    d = get_visible_donation(db, donation_id, user)
    stmt = select(MatchRecommendation).where(MatchRecommendation.donation_id == d.id)
    if not include_history:
        stmt = stmt.where(MatchRecommendation.status.in_(("proposed", "accepted")))
    if user.role == "ngo" and d.donor_id != user.id:
        # NGOs only see their own recommendation rows, not competitors'.
        stmt = stmt.where(MatchRecommendation.ngo_id == user.ngo_profile.id)
    rows = db.scalars(stmt.order_by(MatchRecommendation.created_at.desc(), MatchRecommendation.rank)).all()
    return [match_out(m) for m in rows]


@router.post("/donation/{donation_id}/run", response_model=list[MatchOut])
def rerun_matching(donation_id: int, user: User = Depends(require_roles("donor", "admin")),
                   db: Session = Depends(get_db)):
    d = get_visible_donation(db, donation_id, user)
    if user.role == "donor" and d.donor_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Donation not found")
    created = generate_matches(db, d, user.id)
    db.commit()
    return [match_out(m) for m in created]


@router.post("/{match_id}/accept", response_model=MatchOut)
def accept(match_id: int, user: User = Depends(require_roles("ngo")), db: Session = Depends(get_db)):
    return match_out(accept_match(db, match_id, user))


@router.post("/{match_id}/reject", response_model=MatchOut)
def reject(match_id: int, body: RejectRequest, user: User = Depends(require_roles("ngo")),
           db: Session = Depends(get_db)):
    return match_out(reject_match(db, match_id, user, body.reason))
