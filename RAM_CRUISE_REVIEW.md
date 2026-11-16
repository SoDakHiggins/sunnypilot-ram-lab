# Ram cruise development lab — candidate map-clock correction

This review branch contains the offline trace reviewer plus a candidate correction
to GPS timestamp handling in the map speed-limit resolver. That correction changes
which map targets can reach speed planning. It has not been installed on a comma.
Do not install this branch: isolated source tests are not full-stack validation.
No validated driving fix or installation package is provided.

## How this fits together

GitHub stores the code and its history. This fork is a separate development copy
of sunnypilot. Sunnylink is the dashboard for an installed device; it does not
automatically deploy commits from this repository. A future device build would
need a deliberate installation path, backup, rollback procedure and validation.
No device installation, update, remote-access change or setting change was made.

## First reproducible source issue

The installed resolver subtracts `gps_data.unixTimestampMillis` (Unix calendar
time) from `time.monotonic()` (a clock with an unrelated origin). With normal
Unix timestamps this produces a large negative age, so an old GPS fix can pass
the freshness check. The same mismatch in distance calculation can put an
upcoming limit at an unrealistically large distance instead of anticipating it.
`system/ubloxd/ubloxd.py` assigns this GPS field from UTC, confirming its clock
domain. This is a source-level finding, not a diagnosis of the reported incident.

The candidate uses Unix time for both calculations, rejects negative/future ages,
and prevents negative travelled distance if the clock shifts between calculations.
It does not change the desired deceleration, curve-speed thresholds, retained
last-valid-limit behavior, cruise engagement or CAN commands.

### Validation performed

| Check | Installed baseline | Candidate |
| --- | --- | --- |
| Fresh GPS accepted | Pass | Pass |
| GPS older than 10 seconds rejected | Fail | Pass |
| Future GPS rejected | Fail | Pass |
| Missing/zero timestamp rejected | Pass | Pass |
| Exactly 10-second age accepted | Pass | Pass |
| Just over 10-second age rejected | Fail | Pass |
| Two-second fix age updates distance correctly | Fail | Pass |
| Passed waypoint distance clamps to zero | Fail | Pass |

All 25 isolated unit checks pass: 8 map-clock checks, 8 existing ICBM behavior
checks and 9 trace-reviewer checks. Baseline runs intentionally retain the five
map-clock failures to demonstrate that the tests detect the original problem.
The source-method harness executes the actual method bodies with synthetic
messages and injected clocks; generated Cap'n Proto and full runtime dependencies
are unavailable here. The ICBM harness uses enum/message stand-ins. There has been
no vehicle simulation, full upstream-suite run, hardware test or road test.

```sh
python3 -m unittest test_ram_map_clock.py test_ram_icbm_source.py test_ram_cruise_review.py -v
RAM_RESOLVER_BASELINE=1 python3 -m unittest test_ram_map_clock.py -v
```

### What remains unresolved

- Whether this clock mismatch contributed to the actual 55-mph selection.
- Whether that selection came from a map value, retained limit, or factory resume.
- Last-valid speed limits may still be retained after current input becomes invalid;
  this candidate deliberately does not redesign that behavior.
- ICBM consumes the target speed, not the planner's acceleration request. The
  eight source checks confirm this and manual-button/cancel/override behavior,
  but they cannot establish real Ram braking smoothness or CAN timing.
- A stale GPS fix and an outdated map are separate issues; this correction does
  not prove that the map data itself is current or correct.
- The installed wall clock must be checked against GPS during actual-log replay.
  Rejecting future GPS ages is conservative input rejection, but behavior during
  device clock adjustment must be evaluated before any deployment.

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
