"""Loading and validating the scheduling input data from a JSON config file."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any, Optional
from .errors import ConfigError
from .rules import build_rules
__all__ = [
    "ConfigError",
    "DEFAULT_OBJECTIVES",
    "Employee",
    "RuleSpec",
    "ScheduleConfig",
    "Shift",
    "StaffRequirement",
    "TimeOff",
    "load_config",
    "parse_config",
]
DEFAULT_SHIFT_HOURS = 8.0
OBJECTIVE_TERMS = ("cost", "balance")
DEFAULT_OBJECTIVES = ("cost", "balance")
@dataclass(frozen=True)
class Employee:
    name: str
    roles: tuple[str, ...]
    hourly_rate: float = 0.0
@dataclass(frozen=True)
class Shift:
    name: str
    hours: float = DEFAULT_SHIFT_HOURS
@dataclass(frozen=True)
class StaffRequirement:
    """Headcount bounds for employees holding `role` on `day`/`shift`.
    `max_count` of None means no upper limit.
    """
    day: str
    shift: str
    role: str
    min_count: int
    max_count: Optional[int] = None
@dataclass(frozen=True)
class TimeOff:
    """`employee` cannot be scheduled on `day`/`shift`."""
    employee: str
    day: str
    shift: str
@dataclass(frozen=True)
class RuleSpec:
    """A rule to apply, by registered name, with its parameters."""
    type: str
    params: dict[str, Any] = field(default_factory=dict)
@dataclass(frozen=True)
class ScheduleConfig:
    employees: tuple[Employee, ...]
    days: tuple[str, ...]
    shifts: tuple[Shift, ...]
    min_staff_default: int
    min_staff: tuple[StaffRequirement, ...]
    time_off: tuple[TimeOff, ...]
    max_shifts_per_employee: int
    rules: tuple[RuleSpec, ...] = ()
    # Optimisation terms after coverage, in priority order.
    objectives: tuple[str, ...] = DEFAULT_OBJECTIVES
    currency: str = ""
    @property
    def employee_names(self) -> tuple[str, ...]:
        return tuple(e.name for e in self.employees)
    @property
    def shift_names(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.shifts)
    @property
    def roles(self) -> tuple[str, ...]:
        """All roles, in order of first appearance among the employees."""
        seen: dict[str, None] = {}
        for e in self.employees:
            for role in e.roles:
                seen.setdefault(role, None)
        return tuple(seen)
    def members_by_role(self) -> dict[str, tuple[str, ...]]:
        members: dict[str, list[str]] = {role: [] for role in self.roles}
        for e in self.employees:
            for role in e.roles:
                members[role].append(e.name)
        return {role: tuple(names) for role, names in members.items()}
    def requirements(self) -> dict[tuple[str, str, str], tuple[int, Optional[int]]]:
        """(day, shift, role) -> (min_count, max_count), with defaults applied."""
        explicit = {
            (r.day, r.shift, r.role): (r.min_count, r.max_count) for r in self.min_staff
        }
        return {
            (d, s, role): explicit.get((d, s, role), (self.min_staff_default, None))
            for d in self.days
            for s in self.shift_names
            for role in self.roles
        }
    @cached_property
    def _employees_by_name(self) -> dict[str, Employee]:
        return {e.name: e for e in self.employees}
    @cached_property
    def _shifts_by_name(self) -> dict[str, Shift]:
        return {s.name: s for s in self.shifts}
    def shift_cost_cents(self, employee: str, shift: str) -> int:
        """Cost of one shift for one employee, in whole cents."""
        rate = self._employees_by_name[employee].hourly_rate
        hours = self._shifts_by_name[shift].hours
        return round(rate * hours * 100)
def load_config(path: str | Path) -> ScheduleConfig:
    """Read a JSON config file from disk and validate it."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Config file {path} is not valid JSON: {exc}") from exc
    return parse_config(raw)
def parse_config(raw: Any) -> ScheduleConfig:
    """Validate an already-decoded config dictionary and build a ScheduleConfig."""
    if not isinstance(raw, dict):
        raise ConfigError("Top-level config must be a JSON object")
    days = _unique_strings(raw, "days")
    shifts = _parse_shifts(raw)
    employees = _parse_employees(raw)
    roles = {role for e in employees for role in e.roles}
    employee_names = {e.name for e in employees}
    shift_names = {s.name for s in shifts}
    min_staff_default = _non_negative_int(raw.get("min_staff_default", 1), "min_staff_default")
    max_shifts = _non_negative_int(
        raw.get("max_shifts_per_employee", len(days) * len(shifts)),
        "max_shifts_per_employee",
    )
    config = ScheduleConfig(
        employees=tuple(employees),
        days=tuple(days),
        shifts=tuple(shifts),
        min_staff_default=min_staff_default,
        min_staff=tuple(_parse_min_staff(raw.get("min_staff", []), days, shift_names, roles)),
        time_off=tuple(_parse_time_off(raw.get("time_off", []), employee_names, days, shift_names)),
        max_shifts_per_employee=max_shifts,
        rules=tuple(_parse_rules(raw.get("rules", []))),
        objectives=tuple(_parse_objectives(raw.get("objectives", list(DEFAULT_OBJECTIVES)))),
        currency=_string_value(raw.get("currency", ""), "currency"),
    )
    # Validate rule parameters now, so mistakes are reported as config errors.
    build_rules(config)
    return config
# --- section parsers ---------------------------------------------------------
def _parse_employees(raw: dict) -> list[Employee]:
    if "employees" not in raw:
        raise ConfigError("Missing required key: 'employees'")
    entries = raw["employees"]
    if not isinstance(entries, list) or not entries:
        raise ConfigError("'employees' must be a non-empty list")
    employees: list[Employee] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigError(f"employees[{i}] must be an object")
        name = _non_empty_string(entry.get("name"), f"employees[{i}].name")
        roles = _parse_roles(entry, i, name)
        rate = _number(entry.get("hourly_rate", 0), f"employees[{i}].hourly_rate")
        employees.append(Employee(name=name, roles=roles, hourly_rate=rate))
    names = [e.name for e in employees]
    if len(set(names)) != len(names):
        raise ConfigError("Employee names must be unique")
    return employees
def _parse_roles(entry: dict, index: int, name: str) -> tuple[str, ...]:
    """An employee has 'role' (one string), 'roles' (a list), or both."""
    roles: list[str] = []
    if "role" in entry:
        roles.append(_non_empty_string(entry["role"], f"employees[{index}].role"))
    if "roles" in entry:
        values = entry["roles"]
        if not isinstance(values, list) or not values:
            raise ConfigError(f"employees[{index}].roles must be a non-empty list")
        roles.extend(_non_empty_string(v, f"employees[{index}].roles") for v in values)
    if not roles:
        raise ConfigError(f"employees[{index}] ('{name}') needs 'role' or 'roles'")
    return tuple(dict.fromkeys(roles))  # remove duplicates, keep order
def _parse_shifts(raw: dict) -> list[Shift]:
    """Shifts are given as a name, or as {"name": ..., "hours": ...}."""
    if "shifts" not in raw:
        raise ConfigError("Missing required key: 'shifts'")
    entries = raw["shifts"]
    if not isinstance(entries, list) or not entries:
        raise ConfigError("'shifts' must be a non-empty list")
    shifts: list[Shift] = []
    for i, entry in enumerate(entries):
        if isinstance(entry, str):
            shifts.append(Shift(name=_non_empty_string(entry, f"shifts[{i}]")))
        elif isinstance(entry, dict):
            name = _non_empty_string(entry.get("name"), f"shifts[{i}].name")
            hours = _number(entry.get("hours", DEFAULT_SHIFT_HOURS), f"shifts[{i}].hours", positive=True)
            shifts.append(Shift(name=name, hours=hours))
        else:
            raise ConfigError(f"shifts[{i}] must be a string or an object with 'name'")
    names = [s.name for s in shifts]
    if len(set(names)) != len(names):
        raise ConfigError("'shifts' contains duplicate entries")
    return shifts
def _parse_min_staff(
    entries: Any, days: list[str], shifts: set[str], roles: set[str]
) -> list[StaffRequirement]:
    if not isinstance(entries, list):
        raise ConfigError("'min_staff' must be a list")
    requirements: list[StaffRequirement] = []
    seen: set[tuple[str, str, str]] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigError(f"min_staff[{i}] must be an object")
        day, shift, role = entry.get("day"), entry.get("shift"), entry.get("role")
        _check_member(day, days, f"min_staff[{i}].day")
        _check_member(shift, shifts, f"min_staff[{i}].shift")
        _check_member(role, roles, f"min_staff[{i}].role")
        # 'min' is the current name; 'count' is accepted for older configs.
        if "min" in entry and "count" in entry:
            raise ConfigError(f"min_staff[{i}] has both 'min' and 'count'; use only 'min'")
        min_key = "min" if "min" in entry else "count"
        min_count = _non_negative_int(entry.get(min_key, 0), f"min_staff[{i}].{min_key}")
        max_count = None
        if entry.get("max") is not None:
            max_count = _non_negative_int(entry["max"], f"min_staff[{i}].max")
            if max_count < min_count:
                raise ConfigError(f"min_staff[{i}]: 'max' ({max_count}) is below 'min' ({min_count})")
        key = (day, shift, role)
        if key in seen:
            raise ConfigError(f"Duplicate min_staff entry for {day}/{shift}/{role}")
        seen.add(key)
        requirements.append(
            StaffRequirement(day=day, shift=shift, role=role, min_count=min_count, max_count=max_count)
        )
    return requirements
def _parse_time_off(
    entries: Any, employee_names: set[str], days: list[str], shifts: set[str]
) -> list[TimeOff]:
    if not isinstance(entries, list):
        raise ConfigError("'time_off' must be a list")
    result: list[TimeOff] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigError(f"time_off[{i}] must be an object")
        employee = entry.get("employee")
        _check_member(employee, employee_names, f"time_off[{i}].employee")
        _check_member(entry.get("day"), days, f"time_off[{i}].day")
        _check_member(entry.get("shift"), shifts, f"time_off[{i}].shift")
        result.append(TimeOff(employee=employee, day=entry["day"], shift=entry["shift"]))
    return result
def _parse_rules(entries: Any) -> list[RuleSpec]:
    """Each rule is {"type": "<name>", ...parameters}."""
    if not isinstance(entries, list):
        raise ConfigError("'rules' must be a list")
    specs: list[RuleSpec] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigError(f"rules[{i}] must be an object with a 'type'")
        rule_type = _non_empty_string(entry.get("type"), f"rules[{i}].type")
        params = {k: v for k, v in entry.items() if k != "type"}
        specs.append(RuleSpec(type=rule_type, params=params))
    return specs
def _parse_objectives(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ConfigError("'objectives' must be a list")
    for term in value:
        if term not in OBJECTIVE_TERMS:
            raise ConfigError(f"'objectives' entry {term!r} must be one of {list(OBJECTIVE_TERMS)}")
    if len(set(value)) != len(value):
        raise ConfigError("'objectives' contains duplicate entries")
    return list(value)
# --- primitive validators ----------------------------------------------------
def _unique_strings(raw: dict, key: str) -> list[str]:
    if key not in raw:
        raise ConfigError(f"Missing required key: '{key}'")
    values = raw[key]
    if not isinstance(values, list) or not values:
        raise ConfigError(f"'{key}' must be a non-empty list")
    for v in values:
        _non_empty_string(v, key)
    if len(set(values)) != len(values):
        raise ConfigError(f"'{key}' contains duplicate entries")
    return list(values)
def _non_empty_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"'{where}' must be a non-empty string, got {value!r}")
    return value
def _string_value(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"'{where}' must be a string, got {value!r}")
    return value
def _number(value: Any, where: str, *, positive: bool = False) -> float:
    # bool is a subclass of int in Python, so exclude it explicitly.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"'{where}' must be a number, got {value!r}")
    if value < 0 or (positive and value == 0):
        raise ConfigError(f"'{where}' must be {'positive' if positive else 'non-negative'}, got {value!r}")
    return float(value)
def _check_member(value: Any, allowed: Any, where: str) -> None:
    if not isinstance(value, str) or value not in allowed:
        raise ConfigError(f"{where} = {value!r} is not one of {sorted(allowed)}")
def _non_negative_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"'{where}' must be a non-negative integer, got {value!r}")
    return value
