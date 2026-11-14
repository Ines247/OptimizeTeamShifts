"""Pluggable scheduling rules.
A rule is a class registered under a name. The config lists rules by name
with parameters, and each rule adds hard constraints through a ModelContext.
To add a rule: subclass `Rule`, set `name` and `allowed_params`, implement
`validate` and `apply`, and decorate the class with `@register_rule`.
The solver itself does not need to change.
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Any, ClassVar, Mapping
from .errors import ConfigError
if TYPE_CHECKING:  # imported only for type hints, avoids a runtime import cycle
    from .config import ScheduleConfig
    from .context import ModelContext
_REGISTRY: dict[str, type["Rule"]] = {}
def register_rule(cls: type["Rule"]) -> type["Rule"]:
    if not cls.name:
        raise TypeError(f"{cls.__name__} must set a non-empty `name`")
    if cls.name in _REGISTRY:
        raise ValueError(f"Rule name '{cls.name}' is already registered")
    _REGISTRY[cls.name] = cls
    return cls
def available_rules() -> list[str]:
    return sorted(_REGISTRY)
class Rule:
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    allowed_params: ClassVar[tuple[str, ...]] = ()
    def __init__(self, params: Mapping[str, Any], config: "ScheduleConfig") -> None:
        self.params = dict(params)
        self.config = config
        unknown = set(self.params) - set(self.allowed_params)
        if unknown:
            raise ConfigError(
                f"rule '{self.name}': unknown parameter(s) {sorted(unknown)}; "
                f"expected {list(self.allowed_params)}"
            )
        self.validate()
    def validate(self) -> None:
        """Raise ConfigError if the parameters are invalid. Override as needed."""
    def apply(self, ctx: "ModelContext") -> None:
        raise NotImplementedError
    # --- helpers for subclasses ---
    def _int_param(self, key: str, minimum: int) -> int:
        value = self.params.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ConfigError(f"rule '{self.name}': '{key}' must be an integer >= {minimum}, got {value!r}")
        return value
    def _positive_number_param(self, key: str) -> float:
        value = self.params.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ConfigError(f"rule '{self.name}': '{key}' must be a positive number, got {value!r}")
        return float(value)
    def _shift_param(self, key: str) -> str:
        value = self.params.get(key)
        if not isinstance(value, str) or value not in self.config.shift_names:
            raise ConfigError(
                f"rule '{self.name}': '{key}' = {value!r} is not one of {list(self.config.shift_names)}"
            )
        return value
@register_rule
class ForbiddenSequence(Rule):
    name = "forbidden_sequence"
    description = "Nobody works `first` on one day and `then` on the next (e.g. no Evening followed by Morning)."
    allowed_params = ("first", "then")
    def validate(self) -> None:
        self.first = self._shift_param("first")
        self.then = self._shift_param("then")
    def apply(self, ctx: "ModelContext") -> None:
        # "Next day" means the next entry in `days`.
        days = self.config.days
        for e in self.config.employee_names:
            for today, tomorrow in zip(days, days[1:]):
                ctx.require(
                    ctx.work(e, today, self.first) + ctx.work(e, tomorrow, self.then) <= 1,
                    f"forbidden sequence {self.first}->{self.then}: {e} {today} to {tomorrow}",
                )
@register_rule
class MaxConsecutiveDays(Rule):
    name = "max_consecutive_days"
    description = "No employee works more than `max` days in a row. Days are taken in `days` order."
    allowed_params = ("max",)
    def validate(self) -> None:
        self.max_days = self._int_param("max", minimum=1)
    def apply(self, ctx: "ModelContext") -> None:
        days, shifts = self.config.days, self.config.shift_names
        window = self.max_days + 1
        for e in self.config.employee_names:
            # One shift per day is a core rule, so "works day d" is 0 or 1 and
            # a window of max+1 consecutive days can hold at most `max` worked days.
            for start in range(len(days) - window + 1):
                block = days[start : start + window]
                worked = sum(ctx.work(e, d, s) for d in block for s in shifts)
                ctx.require(
                    worked <= self.max_days,
                    f"max {self.max_days} consecutive days: {e} {block[0]} to {block[-1]}",
                )
@register_rule
class MaxWeeklyHours(Rule):
    name = "max_weekly_hours"
    description = "No employee is scheduled for more than `max_hours` hours in total (uses shift hours)."
    allowed_params = ("max_hours",)
    def validate(self) -> None:
        self.max_hours = self._positive_number_param("max_hours")
    def apply(self, ctx: "ModelContext") -> None:
        # Hours are scaled to hundredths so the constraint stays integer.
        hours = {s.name: round(s.hours * 100) for s in self.config.shifts}
        limit = round(self.max_hours * 100)
        for e in self.config.employee_names:
            total = sum(
                hours[s] * ctx.work(e, d, s)
                for d in self.config.days
                for s in self.config.shift_names
            )
            ctx.require(total <= limit, f"max {self.max_hours:g} hours per week: {e}")
def build_rules(config: "ScheduleConfig") -> list[Rule]:
    """Instantiate every rule listed in the config, validating parameters."""
    rules: list[Rule] = []
    for spec in config.rules:
        cls = _REGISTRY.get(spec.type)
        if cls is None:
            raise ConfigError(
                f"Unknown rule type '{spec.type}'. Available rules: {available_rules()}"
            )
        rules.append(cls(spec.params, config))
    return rules
