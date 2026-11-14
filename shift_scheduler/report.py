"""Human-readable rendering of a ScheduleResult."""
from __future__ import annotations
from .config import ScheduleConfig
from .scheduler import ScheduleResult
def format_result(config: ScheduleConfig, result: ScheduleResult) -> str:
    if not result.feasible:
        lines = [f"No schedule satisfies all hard constraints (solver status: {result.status})."]
        if result.conflicts:
            lines.append("Conflicting constraints:")
            lines.extend(f"  - {label}" for label in result.conflicts)
        return "\n".join(lines)
    lines: list[str] = []
    if result.status == "OPTIMAL":
        lines.append("Optimal Schedule Found!")
    else:
        lines.append("Feasible Schedule Found (not proven optimal).")
    lines.append("")
    roles = {e.name: ", ".join(e.roles) for e in config.employees}
    for d in config.days:
        lines.append(f"--- Day: {d} ---")
        for s in config.shift_names:
            assigned = [_label(name, roles) for name in result.assignments[(d, s)]]
            lines.append(f"  {s} Shift: {', '.join(assigned) if assigned else 'None'}")
    if result.shortfalls:
        lines.append("")
        lines.append("Coverage shortfalls (people missing from minimum staffing):")
        for (d, s, role), missing in sorted(result.shortfalls.items()):
            lines.append(f"  {d} {s} {role}: {missing} short")
    lines.append("")
    lines.append("Total Shifts per Employee:")
    for name in config.employee_names:
        lines.append(f"  {_label(name, roles)}: {result.totals[name]} shifts")
    lines.append("")
    currency = f" {config.currency}" if config.currency else ""
    lines.append(f"Total cost: {result.cost:,.2f}{currency}")
    return "\n".join(lines)
def _label(name: str, roles: dict[str, str]) -> str:
    return f"{name} ({roles[name]})"
