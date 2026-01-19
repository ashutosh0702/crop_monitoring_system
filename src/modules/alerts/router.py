"""
Alerts router for NDVI threshold monitoring and notifications.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List

from src.database import get_db
from src.models import User, Farm, Alert
from src.modules.alerts import schemas


router = APIRouter(prefix="/alerts", tags=["Alerts"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """Get current authenticated user from JWT token."""
    from src.core import security
    
    try:
        payload = security.jwt.decode(
            token,
            security.settings.SECRET_KEY,
            algorithms=[security.settings.ALGORITHM]
        )
        phone = payload.get("sub")
        if phone is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = db.query(User).filter(User.phone_number == phone).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    
    return user


@router.get("/", response_model=List[schemas.AlertResponse])
def get_alerts(
    unread_only: bool = False,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all alerts for the current user's farms.
    
    - **unread_only**: Filter to show only unread alerts
    - **limit**: Maximum number of alerts to return
    """
    # Get user's farm IDs
    farm_ids = [farm.id for farm in db.query(Farm).filter(Farm.owner_id == current_user.id).all()]
    
    if not farm_ids:
        return []
    
    # Query alerts
    query = db.query(Alert).filter(Alert.farm_id.in_(farm_ids))
    
    if unread_only:
        query = query.filter(Alert.is_read == False)
    
    alerts = query.order_by(Alert.created_at.desc()).limit(limit).all()
    
    # Add farm names
    farm_names = {
        farm.id: farm.name
        for farm in db.query(Farm).filter(Farm.id.in_(farm_ids)).all()
    }
    
    result = []
    for alert in alerts:
        result.append({
            "id": str(alert.id),
            "farm_id": str(alert.farm_id),
            "farm_name": farm_names.get(alert.farm_id, "Unknown"),
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "message": alert.message,
            "is_read": alert.is_read,
            "created_at": alert.created_at,
        })
    
    return result


@router.get("/summary", response_model=schemas.AlertSummary)
def get_alert_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get summary of alerts for the current user.
    
    Returns total count, unread count, and breakdown by severity.
    """
    # Get user's farm IDs
    farm_ids = [farm.id for farm in db.query(Farm).filter(Farm.owner_id == current_user.id).all()]
    
    if not farm_ids:
        return {"total": 0, "unread": 0, "by_severity": {}}
    
    # Count total alerts
    total = db.query(Alert).filter(Alert.farm_id.in_(farm_ids)).count()
    
    # Count unread
    unread = db.query(Alert).filter(
        Alert.farm_id.in_(farm_ids),
        Alert.is_read == False
    ).count()
    
    # Group by severity
    severity_counts = db.query(
        Alert.severity,
        func.count(Alert.id)
    ).filter(
        Alert.farm_id.in_(farm_ids)
    ).group_by(Alert.severity).all()
    
    by_severity = {severity: count for severity, count in severity_counts}
    
    return {
        "total": total,
        "unread": unread,
        "by_severity": by_severity
    }


@router.get("/{farm_id}", response_model=List[schemas.AlertResponse])
def get_farm_alerts(
    farm_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get alerts for a specific farm.
    """
    # Verify farm ownership
    farm = db.query(Farm).filter(
        Farm.id == farm_id,
        Farm.owner_id == current_user.id
    ).first()
    
    if not farm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Farm not found"
        )
    
    alerts = db.query(Alert).filter(
        Alert.farm_id == farm_id
    ).order_by(Alert.created_at.desc()).all()
    
    return [{
        "id": str(alert.id),
        "farm_id": str(alert.farm_id),
        "farm_name": farm.name,
        "alert_type": alert.alert_type,
        "severity": alert.severity,
        "message": alert.message,
        "is_read": alert.is_read,
        "created_at": alert.created_at,
    } for alert in alerts]


@router.post("/mark-read")
def mark_alerts_read(
    request: schemas.AlertMarkReadRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Mark alerts as read.
    
    - **alert_ids**: List of alert UUIDs to mark as read
    """
    # Get user's farm IDs for validation
    farm_ids = [farm.id for farm in db.query(Farm).filter(Farm.owner_id == current_user.id).all()]
    
    # Update alerts
    updated = db.query(Alert).filter(
        Alert.id.in_(request.alert_ids),
        Alert.farm_id.in_(farm_ids)
    ).update({Alert.is_read: True}, synchronize_session=False)
    
    db.commit()
    
    return {"message": f"Marked {updated} alerts as read"}


@router.delete("/{alert_id}")
def delete_alert(
    alert_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete an alert.
    """
    # Get user's farm IDs for validation
    farm_ids = [farm.id for farm in db.query(Farm).filter(Farm.owner_id == current_user.id).all()]
    
    alert = db.query(Alert).filter(
        Alert.id == alert_id,
        Alert.farm_id.in_(farm_ids)
    ).first()
    
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found"
        )
    
    db.delete(alert)
    db.commit()
    
    return {"message": "Alert deleted"}
