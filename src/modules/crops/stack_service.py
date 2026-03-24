"""
Persistence helpers for crop index stacks.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy.orm import Session

from src.models import CropIndexStack


class CropIndexStackService:
    """Store and retrieve persisted crop index stacks."""

    def __init__(self, db: Session):
        self.db = db

    def get_latest_stack(self, farm_id: str) -> Optional[Dict[str, Any]]:
        farm_uuid = uuid.UUID(farm_id)
        stack = (
            self.db.query(CropIndexStack)
            .filter(CropIndexStack.farm_id == farm_uuid)
            .order_by(CropIndexStack.scene_date.desc())
            .first()
        )
        return None if stack is None else stack.to_dict()

    def list_stacks(self, farm_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        farm_uuid = uuid.UUID(farm_id)
        stacks = (
            self.db.query(CropIndexStack)
            .filter(CropIndexStack.farm_id == farm_uuid)
            .order_by(CropIndexStack.scene_date.desc())
            .limit(limit)
            .all()
        )
        return [stack.to_dict() for stack in stacks]

    def save_stack(self, farm_id: str, stack_payload: Dict[str, Any]) -> Dict[str, Any]:
        stack = self._upsert_stack(farm_id, stack_payload)
        self.db.commit()
        self.db.refresh(stack)
        return stack.to_dict()

    def save_many(self, farm_id: str, stack_payloads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        records = [self._upsert_stack(farm_id, payload) for payload in stack_payloads]
        self.db.commit()
        for record in records:
            self.db.refresh(record)
        return [record.to_dict() for record in records]

    def _upsert_stack(self, farm_id: str, stack_payload: Dict[str, Any]) -> CropIndexStack:
        scene_date = self._parse_datetime(stack_payload["scene_date"])
        source = stack_payload.get("source", "sentinel-2")
        farm_uuid = uuid.UUID(farm_id)

        stack = (
            self.db.query(CropIndexStack)
            .filter(
                CropIndexStack.farm_id == farm_uuid,
                CropIndexStack.scene_date == scene_date,
                CropIndexStack.satellite_source == source,
            )
            .first()
        )

        if stack is None:
            stack = CropIndexStack(
                id=uuid.uuid4(),
                farm_id=farm_uuid,
                scene_date=scene_date,
            )
            self.db.add(stack)

        stack.stack_tiff_url = stack_payload["stack_tiff_url"]
        stack.indices = stack_payload["indices"]
        stack.band_order = stack_payload["band_order"]
        stack.satellite_source = source
        stack.cloud_cover = stack_payload.get("cloud_cover")
        return stack

    def _parse_datetime(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value)
