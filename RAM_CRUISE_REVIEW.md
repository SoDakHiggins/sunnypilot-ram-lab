# Ram cruise development lab — phase 1

This branch adds an offline trace reviewer, synthetic examples, and regression checks.
It does not modify steering, acceleration, braking, CAN safety, driver monitoring,
startup, or software-update configuration. Do not install this branch on a comma.
There is no validated driving fix or installation package in this phase.

## How this fits together

GitHub stores the code and its history. This fork is a separate development copy
of sunnypilot. Sunnylink is the dashboard for an installed device; it does not
automatically deploy commits from this repository. A future device build would
need a deliberate installation path, backup, rollback procedure and validation.
No device installation, update, remote-access change or setting change was made.

## Baseline

- Device observed: comma four, sunnypilot 2026.002.002, release-mici.
- Exact source baseline: `6a17f75c6bcb67c85f252a1acc342d94d5b8a4d2`.
- Vehicle detected by device: `RAM_1500_5TH_GEN`.
- The public fork contains code and artificial fixtures only. Keep actual driving
  data, routes, identifiers, videos and settings exports outside this repository.
- The incident log is unavailable. No reported driving failure is reproduced yet.

## Findings from the matching source

1. `sunnypilot/selfdrive/controls/lib/longitudinal_planner.py`,
   `update_targets` selects the lowest target across cruise, vision curves,
   map curves and speed-limit assist. Its publication includes both `vTarget`
   and `aTarget`, plus the selected source and individual curve targets.
2. `sunnypilot/selfdrive/car/intelligent_cruise_button_management/controller.py`,
   `update_calculations` consumes `LP_SP.vTarget`, rounds to displayed speed units,
   and compares it with `CS.cruiseState.speedCluster`. Its state machine requests
   increase/decrease buttons. It does not use `LP_SP.aTarget`.
3. `opendbc_repo/opendbc/sunnypilot/car/chrysler/icbm.py`, `update` translates
   those requests into Ram cruise-button CAN messages. Factory ACC determines
   the acceleration/braking response. A gentle planner acceleration request alone
   therefore does not guarantee gentle factory-ACC braking.
4. `sunnypilot/selfdrive/car/cruise_ext.py` and `selfdrive/car/cruise.py` contain
   separate software-target and stock-cluster speed paths. Their separation is
   a reason to inspect both values rather than treating one display as proof of
   accepted vehicle commands.
5. `sunnypilot/selfdrive/controls/lib/speed_limit/speed_limit_resolver.py`
   retains a last-valid limit. Current-limit validity and last-valid-limit
   validity are different signals. We have not established where the reported
   55 mph came from; map, previous set speed, initialization and resume behavior
   remain hypotheses.

## Run without the vehicle

Python 3.10+; no extra dependencies for the JSONL analyzer or unit checks:

```sh
python3 -m unittest test_ram_cruise_review.py -v
python3 ram_cruise_review.py --jsonl ram_cruise_demo.jsonl --synthetic
```

The demonstration is invented. It shows a 50-to-30 mph target step, actual
deceleration and a delayed cluster response. It is not this truck's recording.
Flags are review candidates; zero flags never means a drive or controller is safe.

Optional local-log mode, from a fully configured matching sunnypilot development
environment:

```sh
python3 ram_cruise_review.py --log-file /private/path/qlog.zst
```

This adapter reads an existing local file only. It keeps selected speed fields
from carState/carControl/longitudinalPlanSP and excludes location/camera data.
The upstream LogReader dependencies are not bundled. The adapter has field-mapping
unit coverage but has not been exercised against a real qlog/rlog here. Sparse
qlogs may omit messages; stale input is skipped and gaps are flagged. Negative or
unset cruise-speed values are rejected rather than treated as real speeds.

## Normalized trace format

One JSON object per line, strictly increasing `t` in seconds. All speed fields
are meters/second; accelerations are meters/second squared.

Required: `t`, `enabled` (boolean), `v_ego_mps`, `a_ego_mps2`,
`requested_mps`, `cluster_set_mps`, `speed_limit_valid` (boolean), `source`.

Optional: `planned_accel_mps2`, `driver_ceiling_mps`. The ceiling must come from
independent evidence of driver intent; never infer it from the software target.

Review filters: target drop at least 5 mph at a rate at least 10 mph/second;
actual deceleration below -2 m/s²; requested/cluster difference above 5 mph for
at least 3 seconds; requested speed more than 1 mph above an independently
recorded ceiling; limit-assist increase at least 5 mph without a current valid
limit. Gaps above 2 seconds break continuity. These are screening choices,
not recommended controller tuning or validated safety thresholds.

## Next engineering steps

1. Obtain an existing private incident trace if available, or use passive logging
   during ordinary manually controlled driving. Do not recreate hazardous behavior.
2. Identify the selected target source, actual stock cruise response, validity
   flags, engagement/resume buttons and any driver intervention.
3. Add a regression case only after the cause is established. Evaluate explicit
   driver speed ceilings, uncertain-data handling and earlier curve planning in
   offline replay. Do not smooth away a necessary slowdown or relax curve limits
   just to suppress braking.
4. Any future controller change requires software/hardware simulation and
   controlled-course validation. Preserve upstream driver monitoring, braking
   override and CAN actuation safeguards. Offline checks are not vehicle validation.
