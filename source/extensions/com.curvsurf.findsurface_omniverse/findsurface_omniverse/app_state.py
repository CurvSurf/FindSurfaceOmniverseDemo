from dataclasses import dataclass, field
from math import sqrt
import re


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def length(a):
    return sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


@dataclass
class DetectionRecord:
    result_id: str
    generation_before: int
    removed_indices: list[int]
    surface_result: object


TRANSACTION_APPLY_DETECTION = "detection_apply"
TRANSACTION_DELETE_GEOMETRY = "delete_geometry"
TRANSACTION_CANCEL_DETECTION = "cancel_detection"
TRANSACTION_RESET_DETECTION = "reset_detection"
TRANSACTION_GLOBAL_VISIBILITY = "global_visibility"
TRANSACTION_GEOMETRY_VISIBILITY = "geometry_visibility"
TRANSACTION_PARAMETER_CHANGE = "parameter_change"
TRANSACTION_CAMERA_CHANGE = "camera_change"


@dataclass
class StateTransaction:
    event_type: str
    generation_before: int
    generation_after: int
    result_id: str | None = None
    result_log_index: int | None = None
    detection_record: DetectionRecord | None = None
    detection_records: list[DetectionRecord] | None = None
    active_mask_before: list[bool] | None = None
    state_before: dict | None = None
    state_after: dict | None = None


@dataclass
class PointCloudState:
    cloud: object
    active_mask: list[bool] = field(init=False)
    generation: int = 0
    result_log: list[DetectionRecord] = field(default_factory=list)
    transaction_log: list[StateTransaction] = field(default_factory=list)
    transaction_index: int = 0

    def __post_init__(self):
        self.active_mask = [True] * self.cloud.count

    @property
    def points(self):
        return self.cloud.points

    @property
    def point_count(self):
        return self.cloud.count

    @property
    def active_count(self):
        return sum(1 for active in self.active_mask if active)

    @property
    def removed_count(self):
        return self.point_count - self.active_count

    @property
    def results(self):
        return [record.surface_result for record in self.result_log]

    def active_indices(self):
        return [index for index, active in enumerate(self.active_mask) if active]

    def next_result_id(self, result_type):
        pattern = re.compile(rf"^{re.escape(str(result_type))}_(\d+)$")
        highest = 0
        for result in self.results:
            if getattr(result, "type", None) != result_type:
                continue
            match = pattern.match(str(getattr(result, "id", "")))
            if match:
                highest = max(highest, int(match.group(1)))
        return f"{result_type}_{highest + 1}"

    def apply_result(self, result):
        generation_before = self.generation
        removed = sorted({index for index in result.inlier_indices if 0 <= index < self.point_count})
        record = DetectionRecord(result.id, generation_before, removed, result)
        for index in removed:
            self.active_mask[index] = False
        self.generation += 1
        self.result_log.append(record)
        self._append_transaction(
            StateTransaction(
                TRANSACTION_APPLY_DETECTION,
                generation_before,
                self.generation,
                result_id=result.id,
                result_log_index=len(self.result_log) - 1,
                detection_record=record,
            )
        )
        return record

    @property
    def can_undo(self):
        return self.transaction_index > 0

    @property
    def can_redo(self):
        return self.transaction_index < len(self.transaction_log)

    def undo_last(self):
        if self.can_undo:
            transaction = self.transaction_log[self.transaction_index - 1]
            result = self._undo_transaction(transaction)
            self.transaction_index -= 1
            self.generation = transaction.generation_before
            return result
        return None

    def redo_last(self):
        if not self.can_redo:
            return None
        transaction = self.transaction_log[self.transaction_index]
        result = self._redo_transaction(transaction)
        self.transaction_index += 1
        self.generation = transaction.generation_after
        return result

    def go_to_transaction_index(self, index):
        index = max(0, min(len(self.transaction_log), int(index)))
        changed = False
        while self.transaction_index > index:
            self.undo_last()
            changed = True
        while self.transaction_index < index:
            self.redo_last()
            changed = True
        return changed

    def remove_result(self, result_id, restore_inliers=False):
        for index, record in enumerate(self.result_log):
            if record.result_id != result_id:
                continue
            generation_before = self.generation
            self.result_log.pop(index)
            if restore_inliers:
                for point_index in record.removed_indices:
                    if 0 <= point_index < self.point_count:
                        self.active_mask[point_index] = True
            self.generation += 1
            self._append_transaction(
                StateTransaction(
                    TRANSACTION_CANCEL_DETECTION if restore_inliers else TRANSACTION_DELETE_GEOMETRY,
                    generation_before,
                    self.generation,
                    result_id=result_id,
                    result_log_index=index,
                    detection_record=record,
                )
            )
            return record.surface_result
        return None

    def reset(self):
        had_changes = bool(self.result_log or self.removed_count)
        if had_changes:
            generation_before = self.generation
            self._append_transaction(
                StateTransaction(
                    TRANSACTION_RESET_DETECTION,
                    generation_before,
                    generation_before + 1,
                    detection_records=list(self.result_log),
                    active_mask_before=list(self.active_mask),
                )
            )
        self.active_mask = [True] * self.point_count
        if had_changes:
            self.generation += 1
        self.result_log.clear()

    def record_state_change(self, event_type, state_before, state_after, result_id=None):
        if state_before == state_after:
            return None
        transaction = StateTransaction(
            str(event_type),
            self.generation,
            self.generation,
            result_id=result_id,
            state_before=dict(state_before or {}),
            state_after=dict(state_after or {}),
        )
        self._append_transaction(transaction)
        return transaction

    def _append_transaction(self, transaction):
        if self.transaction_index < len(self.transaction_log):
            self.transaction_log = self.transaction_log[: self.transaction_index]
        self.transaction_log.append(transaction)
        self.transaction_index = len(self.transaction_log)

    def _undo_transaction(self, transaction):
        if transaction.event_type == TRANSACTION_APPLY_DETECTION:
            record = transaction.detection_record
            if record and self.result_log and self.result_log[-1].result_id == record.result_id:
                self.result_log.pop()
            elif record:
                self._remove_record_instance(record)
            if record:
                for index in record.removed_indices:
                    if 0 <= index < self.point_count:
                        self.active_mask[index] = True
                return record.surface_result
            return None

        if transaction.event_type in (TRANSACTION_DELETE_GEOMETRY, TRANSACTION_CANCEL_DETECTION):
            record = transaction.detection_record
            if not record:
                return None
            insert_at = transaction.result_log_index
            if insert_at is None or insert_at < 0 or insert_at > len(self.result_log):
                insert_at = len(self.result_log)
            self.result_log.insert(insert_at, record)
            if transaction.event_type == TRANSACTION_CANCEL_DETECTION:
                for index in record.removed_indices:
                    if 0 <= index < self.point_count:
                        self.active_mask[index] = False
            return record.surface_result

        if transaction.event_type == TRANSACTION_RESET_DETECTION:
            self.active_mask = list(transaction.active_mask_before or [True] * self.point_count)
            self.result_log = list(transaction.detection_records or [])
            return self.result_log[-1].surface_result if self.result_log else None

        return None

    def _redo_transaction(self, transaction):
        if transaction.event_type == TRANSACTION_APPLY_DETECTION:
            record = transaction.detection_record
            if not record:
                return None
            insert_at = transaction.result_log_index
            if insert_at is None or insert_at < 0 or insert_at > len(self.result_log):
                insert_at = len(self.result_log)
            self.result_log.insert(insert_at, record)
            for index in record.removed_indices:
                if 0 <= index < self.point_count:
                    self.active_mask[index] = False
            return record.surface_result

        if transaction.event_type in (TRANSACTION_DELETE_GEOMETRY, TRANSACTION_CANCEL_DETECTION):
            record = transaction.detection_record
            if not record:
                return None
            self._remove_record_instance(record)
            if transaction.event_type == TRANSACTION_CANCEL_DETECTION:
                for index in record.removed_indices:
                    if 0 <= index < self.point_count:
                        self.active_mask[index] = True
            return record.surface_result

        if transaction.event_type == TRANSACTION_RESET_DETECTION:
            self.active_mask = [True] * self.point_count
            self.result_log.clear()
            records = transaction.detection_records or []
            return records[-1].surface_result if records else None

        return None

    def _remove_record_instance(self, target):
        for index in range(len(self.result_log) - 1, -1, -1):
            record = self.result_log[index]
            if record is target or record.result_id == target.result_id:
                self.result_log.pop(index)
                return record
        return None


def pick_center_point(state):
    active = state.active_indices()
    if not active:
        return None
    center = tuple((state.cloud.bounds_min[axis] + state.cloud.bounds_max[axis]) * 0.5 for axis in range(3))
    return min(active, key=lambda index: length(sub(state.points[index], center)))


__all__ = [
    "DetectionRecord",
    "PointCloudState",
    "StateTransaction",
    "TRANSACTION_APPLY_DETECTION",
    "TRANSACTION_CANCEL_DETECTION",
    "TRANSACTION_CAMERA_CHANGE",
    "TRANSACTION_DELETE_GEOMETRY",
    "TRANSACTION_GEOMETRY_VISIBILITY",
    "TRANSACTION_GLOBAL_VISIBILITY",
    "TRANSACTION_PARAMETER_CHANGE",
    "TRANSACTION_RESET_DETECTION",
    "pick_center_point",
]
