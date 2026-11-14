"""Builds and solves the CP-SAT model for shift assignments.
Core hard constraints (always enforced):
  - time off is respected
  - at most one shift per employee per day
  - per-slot headcount bounds (min and optional max) for each role
  - weekly shift cap per employee
  - any rules listed in the config (see rules.py)
Objective, in priority order:
  1. coverage: minimise the number of missing people (relaxed mode only)
  2. then each term in config.objectives, by default cost, then balance
The priorities are lexicographic. Each term's weight exceeds the largest
possible total of all lower-priority terms, so a higher-priority term is
never traded away for a lower one.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from itertools import product
from typing import Optional
from ortools.sat.python import cp_model
from .config import ScheduleConfig
from .context import ModelContext
from .rules import build_rules
@dataclass
class ScheduleResult:
    feasible: bool
    status: str
    objective: Optional[float] = None
    # (day, shift) -> names of employees working that shift
    assignments: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    # employee name -> number of shifts worked
    totals: dict[str, int] = field(default_factory=dict)
    # (day, shift, role) -> number of people missing from the minimum headcount
    shortfalls: dict[tuple[str, str, str], int] = field(default_factory=dict)
    # total cost of the schedule, in currency units
    cost: float = 0.0
    # strict mode only: labels of the constraints that cannot all hold together
    conflicts: list[str] = field(default_factory=list)
    @property
    def fully_covered(self) -> bool:
        return self.feasible and not self.shortfalls
@dataclass
class BuiltModel:
    model: cp_model.CpModel
    ctx: ModelContext
    shortfalls: dict[tuple[str, str, str], cp_model.IntVar]
    has_objective: bool
def lexicographic_weights(upper_bounds: list[int]) -> list[int]:
    """Weights so that term i outweighs the sum of all later terms.
    Term i is bounded by `upper_bounds[i]`. Working from the last term back,
    each weight is the previous weight times (upper bound + 1).
    """
    weights = [0] * len(upper_bounds)
    multiplier = 1
    for i in reversed(range(len(upper_bounds))):
        weights[i] = multiplier
        multiplier *= upper_bounds[i] + 1
    return weights
def build_model(config: ScheduleConfig, *, relaxed: bool = True) -> BuiltModel:
    model = cp_model.CpModel()
    days, shifts, employees = config.days, config.shift_names, config.employee_names
    x = {
        (e, d, s): model.NewBoolVar(f"work_{e}_{d}_{s}")
        for e, d, s in product(employees, days, shifts)
    }
    ctx = ModelContext(model, x, config, relaxed=relaxed)
    # --- Core hard constraints ---
    for t in config.time_off:
        ctx.require(ctx.work(t.employee, t.day, t.shift) == 0, f"time off: {t.employee} {t.day} {t.shift}")
    for e, d in product(employees, days):
        ctx.require(
            sum(ctx.work(e, d, s) for s in shifts) <= 1,
            f"one shift per day: {e} {d}",
        )
    members = config.members_by_role()
    shortfalls: dict[tuple[str, str, str], cp_model.IntVar] = {}
    coverage_bound = 0  # largest possible total shortfall
    for (d, s, role), (min_count, max_count) in config.requirements().items():
        headcount = sum(ctx.work(e, d, s) for e in members[role])
        if min_count > 0:
            if relaxed:
                short = model.NewIntVar(0, min_count, f"short_{d}_{s}_{role}")
                shortfalls[(d, s, role)] = short
                coverage_bound += min_count
                headcount_or_short = headcount + short
            else:
                headcount_or_short = headcount
            ctx.require(
                headcount_or_short >= min_count,
                f"min staffing {d}/{s}/{role} >= {min_count}",
            )
        if max_count is not None:
            ctx.require(headcount <= max_count, f"max staffing {d}/{s}/{role} <= {max_count}")
    for e in employees:
        ctx.require(
            sum(ctx.work(e, d, s) for d, s in product(days, shifts)) <= config.max_shifts_per_employee,
            f"max {config.max_shifts_per_employee} shifts per week: {e}",
        )
    # --- Rules from the config ---
    for rule in build_rules(config):
        rule.apply(ctx)
    # --- Objective ---
    terms: list[tuple[cp_model.LinearExprT, int]] = []  # (expression, upper bound)
    if shortfalls:
        terms.append((sum(shortfalls.values()), coverage_bound))
    max_possible_load = len(days) * len(shifts)
    for name in config.objectives:
        if name == "cost":
            costs = {(e, d, s): config.shift_cost_cents(e, s) for e, d, s in x}
            terms.append((sum(costs[k] * v for k, v in x.items()), sum(costs.values())))
        elif name == "balance":
            max_load = model.NewIntVar(0, max_possible_load, "max_load")
            for e in employees:
                model.Add(max_load >= sum(x[(e, d, s)] for d, s in product(days, shifts)))
            terms.append((max_load, max_possible_load))
    has_objective = bool(terms)
    if has_objective:
        weights = lexicographic_weights([ub for _, ub in terms])
        model.Minimize(sum(w * expr for (expr, _), w in zip(terms, weights)))
    return BuiltModel(model=model, ctx=ctx, shortfalls=shortfalls, has_objective=has_objective)
def solve(config: ScheduleConfig, *, strict: bool = False) -> ScheduleResult:
    """Solve the scheduling problem.
    By default (relaxed) coverage gaps are allowed and reported in
    `shortfalls`, so a schedule is returned whenever the hard rules alone are
    satisfiable. With `strict=True`, minimum staffing becomes a hard
    constraint. If that is impossible, `conflicts` lists the constraints that
    cannot all hold together.
    """
    built = build_model(config, relaxed=not strict)
    solver = cp_model.CpSolver()
    status = solver.Solve(built.model)
    status_name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        conflicts: list[str] = []
        if strict and status == cp_model.INFEASIBLE:
            conflicts = built.ctx.minimal_conflict(solver.SufficientAssumptionsForInfeasibility())
        return ScheduleResult(feasible=False, status=status_name, conflicts=conflicts)
    assignments = {
        (d, s): [e for e in config.employee_names if solver.Value(built.ctx.work(e, d, s)) == 1]
        for d, s in product(config.days, config.shift_names)
    }
    totals = {
        e: sum(solver.Value(built.ctx.work(e, d, s)) for d, s in product(config.days, config.shift_names))
        for e in config.employee_names
    }
    shortfalls = {
        key: solver.Value(var) for key, var in built.shortfalls.items() if solver.Value(var) > 0
    }
    cost_cents = sum(
        config.shift_cost_cents(e, s) for (d, s), names in assignments.items() for e in names
    )
    return ScheduleResult(
        feasible=True,
        status=status_name,
        objective=solver.ObjectiveValue() if built.has_objective else None,
        assignments=assignments,
        totals=totals,
        shortfalls=shortfalls,
        cost=cost_cents / 100,
    )
