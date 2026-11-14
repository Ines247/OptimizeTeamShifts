"""Shared state passed to rules while the model is being built."""
from __future__ import annotations
from typing import TYPE_CHECKING, Iterable, Union
from ortools.sat.python import cp_model
if TYPE_CHECKING:
    from .config import ScheduleConfig
Constraint = Union[cp_model.BoundedLinearExpression, bool]
class ModelContext:
    """Wraps the CP-SAT model so every hard constraint carries a label.
    In strict mode each labelled constraint is guarded by an enforcement
    literal that is passed as an assumption. If the model is infeasible, the
    solver's assumption core identifies the labels that conflict. In relaxed
    mode constraints are added directly, since no diagnosis is needed.
    """
    def __init__(
        self,
        model: cp_model.CpModel,
        x: dict[tuple[str, str, str], cp_model.IntVar],
        config: "ScheduleConfig",
        relaxed: bool,
    ) -> None:
        self.model = model
        self.x = x
        self.config = config
        self.relaxed = relaxed
        self._labels: dict[int, str] = {}
        self._literals: dict[int, cp_model.IntVar] = {}
    def work(self, employee: str, day: str, shift: str) -> cp_model.IntVar:
        """Boolean variable: 1 if `employee` works `shift` on `day`."""
        return self.x[(employee, day, shift)]
    def require(self, constraint: Constraint, label: str) -> None:
        """Add a hard constraint, labelled for conflict reporting."""
        if isinstance(constraint, bool):
            # Some constraints simplify to a constant, e.g. a headcount over an
            # empty group. Turn that into a constraint the model can hold.
            constraint = self.model.NewConstant(1 if constraint else 0) == 1
        if self.relaxed:
            self.model.Add(constraint)
            return
        enforce = self.model.NewBoolVar(f"enforce_{len(self._labels)}")
        self.model.Add(constraint).OnlyEnforceIf(enforce)
        self.model.AddAssumption(enforce)
        self._labels[enforce.Index()] = label
        self._literals[enforce.Index()] = enforce
    def minimal_conflict(self, core: Iterable[int]) -> list[str]:
        """Shrink an assumption core to a minimal set of labels that still conflicts.
        The solver's core is sufficient but not necessarily minimal, so this
        drops each label in turn and keeps it out only if the remainder is still
        infeasible. Each step is a full solve, which is acceptable for diagnostics.
        """
        keep = [i for i in core if i in self._labels]
        solver = cp_model.CpSolver()
        i = 0
        while i < len(keep):
            trial = keep[:i] + keep[i + 1 :]
            self.model.clear_assumptions()
            self.model.add_assumptions([self._literals[j] for j in trial])
            if solver.Solve(self.model) == cp_model.INFEASIBLE:
                keep = trial  # this label is not needed to conflict
            else:
                i += 1
        self.model.clear_assumptions()
        return [self._labels[j] for j in keep]
Back to top
requirements.txt
