from ortools.sat.python import cp_model

def optimize_team_shifts():
    # Model instance
    model = cp_model.CpModel()

    # --- 1. Data Definitions ---
    employees = ["Alice (Nurse)", "Bob (Nurse)", "Charlie (Doctor)", "Diana (Doctor)"]
    roles = {"Nurse": ["Alice (Nurse)", "Bob (Nurse)"], "Doctor": ["Charlie (Doctor)", "Diana (Doctor)"]}
    
    days = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    shifts = ["Morning", "Evening"] # e.g., Day vs Night

    # Minimum staffing requirements per shift and role
    # Format: (Day, Shift, Role): min_required
    min_staff = {
        ("Mon", "Morning", "Nurse"): 1,
        ("Mon", "Morning", "Doctor"): 1,
        # ... (extend for other days/shifts as needed)
    }

    # Employee unavailability / vacation (Day, Shift) tuples
    # e.g., Alice is unavailable on Monday Morning (vacation/appointment)
    time_off = {
        "Alice (Nurse)": [("Mon", "Morning")]
    }

    # --- 2. Decision Variables ---
    # x[e, d, s] = 1 if employee e works shift s on day d, else 0
    x = {}
    for e in employees:
        for d in days:
            for s in shifts:
                x[(e, d, s)] = model.NewBoolVar(f"work_{e}_{d}_{s}")

    # --- 3. Constraints ---

    # Constraint A: Respect Employee Unavailability / Time-off
    for e, off_list in time_off.items():
        for (d, s) in off_list:
            model.Add(x[(e, d, s)] == 0)

    # Constraint B: Maximum 1 shift per employee per day
    for e in employees:
        for d in days:
            model.Add(sum(x[(e, d, s)] for s in shifts) <= 1)

    # Constraint C: Minimum staffing requirements per role, shift, and day
    for d in days:
        for s in shifts:
            for role, members in roles.items():
                # Default minimum requirement if not explicitly specified is 1
                req = min_staff.get((d, s, role), 1)
                model.Add(sum(x[(e, d, s)] for e in members) >= req)

    # Constraint D: Maximum weekly shifts per employee (prevent burnout, e.g., max 4 shifts out of 5 days)
    max_shifts_per_employee = 4
    for e in employees:
        model.Add(sum(x[(e, d, s)] for d in days for s in shifts) <= max_shifts_per_employee)

    # --- 4. Objective Function: Fair Distribution & Preference Matching ---
    # We want to balance total shifts assigned to each employee to ensure fairness.
    total_shifts = {}
    for e in employees:
        total_shifts[e] = model.NewIntVar(0, len(days) * len(shifts), f"total_{e}")
        model.Add(total_shifts[e] == sum(x[(e, d, s)] for d in days for s in shifts))

    # Minimize the variance in shift load by minimizing the maximum shifts assigned to any single worker
    max_load = model.NewIntVar(0, len(days) * len(shifts), "max_load")
    for e in employees:
        model.Add(max_load >= total_shifts[e])

    model.Minimize(max_load)

    # --- 5. Solve the Model ---
    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print(f"Optimal Schedule Found! (Objective Value: {solver.ObjectiveValue()})\n")
        for d in days:
            print(f"--- Day: {d} ---")
            for s in shifts:
                assigned = [e for e in employees if solver.Value(x[(e, d, s)]) == 1]
                print(f"  {s} Shift: {', '.join(assigned) if assigned else 'None'}")
        print("\nTotal Shifts per Employee:")
        for e in employees:
            print(f"  {e}: {solver.Value(total_shifts[e])} shifts")
    else:
        print("No feasible solution found under the given constraints.")

if __name__ == "__main__":
    optimize_team_shifts()
