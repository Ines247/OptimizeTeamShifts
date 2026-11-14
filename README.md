# OptimizeTeamShifts

A scheduling optimization toold designed to automate and optimize employee shift and role assignments for hospitals and other organizations with rotating workforces. The system considers individual availability and vacation preferences, required time allocations across different roles, minimum and maximum staffing requirements per role or shift, and other operational constraints. Using mathematical optimization algorithms, it generates efficient and balanced schedules that meet organizational staffing needs while accomodating employee preferences and ensuring fair distribution of shifts and responsibilities.

## Usage
Install the dependencies and run the scheduler against a JSON config file:
```bash
pip install -r requirements.txt
python main.py --config config.json      # or: python -m shift_scheduler -c config.json
python main.py --config config.json --strict
```
By default, minimum staffing is treated as a target. If there aren't enough people, the schedule is still produced and the gaps are listed under *Coverage shortfalls*. With `--strict`, minimum staffing is a hard constraint. If no schedule can satisfy every rule, the output lists the minimal set of conflicting constraints.
Exit codes: `0` fully covered schedule, `1` coverage shortfalls or no schedule (strict), `2` config file missing or invalid.

## Configuration

All input data lives in a JSON file. See [`config.json`](config.json) for a working hospital example.
| Key | Required | Description |
| --- | --- | --- |
| `employees` | yes | List of `{"name", "role", "hourly_rate"}`. `role` is one string; `roles` (a list) can be used instead or as well. Names are unique. `hourly_rate` defaults to 0. |
| `days` | yes | Ordered list of day labels. "Next day" for rules means the next entry in this list. |
| `shifts` | yes | List of shift names, or `{"name", "hours"}` objects. Hours default to 8 and drive cost and weekly-hour rules. |
| `min_staff_default` | no (default `1`) | Minimum headcount per role on every day and shift without an explicit entry. |
| `min_staff` | no | List of `{"day", "shift", "role", "min", "max"}`. `max` is optional. `count` is accepted as an alias for `min`. |
| `time_off` | no | List of `{"employee", "day", "shift"}` marking unavailable slots. |
| `max_shifts_per_employee` | no (default: every slot) | Weekly cap on shifts per employee. |
| `rules` | no | Extra hard rules, each `{"type": ..., ...params}`. See below. |
| `objectives` | no (default `["cost", "balance"]`) | Terms optimised after coverage, in priority order. `cost` minimises total pay. `balance` minimises the busiest employee's shift count. |
| `currency` | no | Label shown next to the total cost. |

### Optimisation priorities

1. **Coverage:** minimise people missing from minimum staffing (relaxed mode only).
2. **Then** each entry of `objectives`, in order.
The priorities are strict. A cheaper schedule is never chosen if it leaves a slot short, and load balancing only breaks ties between schedules of equal cost.

### Rules

| Type | Parameters | Meaning |
| --- | --- | --- |
| `forbidden_sequence` | `first`, `then` (shift names) | Nobody works `first` on one day and `then` on the next, e.g. no Evening followed by Morning. |
| `max_consecutive_days` | `max` (integer) | Nobody works more than `max` days in a row. |
| `max_weekly_hours` | `max_hours` (number) | Nobody is scheduled for more than `max_hours` hours in total. |
Add your own by subclassing `shift_scheduler.rules.Rule`, setting `name`, and decorating it with `@register_rule`. See `shift_scheduler/rules.py`.

## Project layout

- `shift_scheduler/config.py`: loads and validates the JSON config (`ConfigError` on bad input).
- `shift_scheduler/rules.py`: the rule registry and built-in rules.
- `shift_scheduler/context.py`: labelled constraints and conflict diagnosis.
- `shift_scheduler/scheduler.py`: builds and solves the CP-SAT model (`build_model`, `solve`).
- `shift_scheduler/report.py`: formats a result as text.
- `shift_scheduler/cli.py`: command-line interface.
- `tests/`: pytest suite.

## Running tests
```bash
pip install -r requirements-dev.txt
pytest
```

## License

This project is licensed under the [MIT License](LICENSE) - see the [LICENSE](LICENSE) file for details.
