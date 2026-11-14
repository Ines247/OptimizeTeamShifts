"""Shift scheduling optimisation driven by a JSON config file."""
from .config import ConfigError, ScheduleConfig, load_config, parse_config
from .context import ModelContext
from .report import format_result
from .rules import Rule, available_rules, register_rule
from .scheduler import ScheduleResult, build_model, solve
__all__ = [
    "ConfigError",
    "ModelContext",
    "Rule",
    "ScheduleConfig",
    "ScheduleResult",
    "available_rules",
    "build_model",
    "format_result",
    "load_config",
    "parse_config",
    "register_rule",
    "solve",
]
