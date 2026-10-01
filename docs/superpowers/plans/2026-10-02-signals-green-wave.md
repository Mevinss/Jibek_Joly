# Visible signals and green-wave freight

User correction: all trains must visibly obey signals; freight needs an Eco marker,
smooth approaches across multiple known green windows, lower actual lateness and a
final fuel comparison. A normal feasible timetable should score 100 when followed;
do not hard-code scores or savings.

Bounded extension of the current corridor. Keep nine stations, the original visual
world and branch. Add a clearly synthetic two-direction normal corridor and retain
the earlier crowded mode. Signals derive from windows, block occupancy, headway
and active incidents. Unknown releases do not generate a promised green.

Use speed transitions with stated demo acceleration/deceleration and a red stopping
envelope. A constant target calculation includes the time/distance of the speed
transition. Planning is advisory, no validated train safety/control claim.

Fuel is an explicitly uncalibrated synthetic litre estimate with visible model
parameters. Compare an Eco run and its counterfactual from identical initial data,
signal windows and incident history, changing only Eco. Show signed results, never
force savings positive. Keep energy proxy and model/diesel outputs distinct.

- [x] Regression tests: initial index, red entry gating, smooth speed transition,
  multiple freight greens, timetable delay, snapshot replay, fuel comparison.
- [x] Extend synthetic package/signals and advisory helper/API.
- [x] Enforce shared signal state; implement smooth kinematics and feasible timetable.
- [x] Add two-lamp 3D signals, freight badges, signal board, final trip result.
- [x] Verify backend/browser desktop and narrow layouts; review and commit.
