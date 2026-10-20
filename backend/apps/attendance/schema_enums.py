"""drf-spectacular enum names of attendance, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: name choices with an import string, e.g.
`{"AttendanceThingStatusEnum": "apps.attendance.models.Thing.Status"}`. Names start with the
app label in PascalCase and must be unique (duplicates stop the settings).
"""

ENUM_NAME_OVERRIDES = {
    "AttendanceOutsideActionEnum": "apps.attendance.models.AttendanceSettings.OutsideAction",
    "AttendanceScheduleKindEnum": "apps.attendance.models.WorkSchedule.Kind",
    "AttendanceShiftStatusEnum": "apps.attendance.models.WorkShift.Status",
    "AttendanceShiftSourceEnum": "apps.attendance.models.WorkShift.Source",
    "AttendanceSwapKindEnum": "apps.attendance.models.ShiftSwap.Kind",
    "AttendanceSwapStatusEnum": "apps.attendance.models.ShiftSwap.Status",
    "AttendanceRecordStatusEnum": "apps.attendance.models.AttendanceRecord.Status",
    "AttendanceRecordSourceEnum": "apps.attendance.models.AttendanceRecord.Source",
    "AttendanceOvertimeStatusEnum": "apps.attendance.models.AttendanceRecord.Overtime",
    "AttendanceRecordFlagEnum": "apps.attendance.models.AttendanceRecord.Flag",
    "AttendanceCorrectionStatusEnum": "apps.attendance.models.AttendanceCorrection.Status",
}
