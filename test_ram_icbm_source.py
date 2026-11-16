"""Exercise the installed ICBM source in isolation; no CAN or vehicle simulation.

Production class/functions are loaded unchanged from AST. Enum and message
stand-ins replace unavailable generated Cap'n Proto bindings. These tests do
not model actual brake response, message timing on the bus, or full engagement.
"""
import ast
from enum import IntEnum
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parent
MPH = 0.44704


class Button(IntEnum):
  decelCruise=0; accelCruise=1; setCruise=2; resumeCruise=3; cancel=4; mainCruise=5

  @property
  def raw(self):
    return self


def load_controller():
  state = IntEnum('State', 'inactive preActive increasing decreasing holding', start=0)
  send = IntEnum('Send', 'none increase decrease', start=0)
  ns = dict(State=state, SendButtonState=send, ButtonType=Button, DT_CTRL=.01,
            CV=NS(MS_TO_KPH=3.6, KPH_TO_MS=1/3.6, MS_TO_MPH=1/MPH, MPH_TO_MS=MPH))
  paths = {
    'opendbc_repo/opendbc/car/__init__.py': {'apply_hysteresis'},
    'sunnypilot/selfdrive/car/cruise_ext.py': {'CRUISE_BUTTON_TIMER', 'update_manual_button_timers'},
    'sunnypilot/selfdrive/car/intelligent_cruise_button_management/helpers.py': {'get_minimum_set_speed'},
    'sunnypilot/selfdrive/car/intelligent_cruise_button_management/controller.py':
      {'ALLOWED_SPEED_THRESHOLD','HYST_GAP','INACTIVE_TIMER','SEND_BUTTONS','IntelligentCruiseButtonManagement'},
  }
  for path, names in paths.items():
    selected = []
    for node in ast.parse((ROOT/path).read_text()).body:
      node_names = {node.name} if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else \
        {target.id for target in node.targets if isinstance(target, ast.Name)} if isinstance(node, ast.Assign) else set()
      if node_names & names:
        selected.append(node)
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0),
                             *selected], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), path, 'exec'), ns)
  return ns['IntelligentCruiseButtonManagement'](NS(), NS(pcmCruiseSpeed=False)), state, send


def messages(target=50, cluster=50, acceleration=-.2):
  return (NS(buttonEvents=[], cruiseState=NS(speedCluster=cluster*MPH)),
          NS(enabled=True, cruiseControl=NS(override=False, cancel=False, resume=False)),
          NS(vTarget=target*MPH, aTarget=acceleration))


def run(controller, msgs, count=45):
  for _ in range(count):
    controller.run(*msgs, is_metric=False)
  return controller.cruise_button


class IcbmSourceTests(unittest.TestCase):
  def test_target_above_cluster_causes_increase(self):
    controller, _, send = load_controller()
    self.assertEqual(run(controller, messages(target=55, cluster=35)), send.increase)

  def test_curve_target_drop_causes_decrease(self):
    controller, _, send = load_controller()
    self.assertEqual(run(controller, messages(target=30, cluster=50)), send.decrease)

  def test_planned_acceleration_does_not_change_button_request(self):
    slow, _, _ = load_controller()
    fast, _, _ = load_controller()
    self.assertEqual(run(slow, messages(target=30, acceleration=-.2)),
                     run(fast, messages(target=30, acceleration=-3.)))

  def test_cluster_acknowledgement_stops_increase(self):
    controller, state, send = load_controller()
    run(controller, messages(target=55, cluster=35))
    self.assertEqual(run(controller, messages(target=55, cluster=55), count=1), send.none)
    self.assertEqual(controller.state, state.holding)

  def test_manual_button_blocks_automatic_command(self):
    controller, _, send = load_controller()
    msgs = messages(target=55, cluster=35)
    run(controller, msgs)
    msgs[0].buttonEvents = [NS(type=Button.accelCruise, pressed=True)]
    self.assertEqual(run(controller, msgs, count=1), send.none)

  def test_cancel_override_resume_and_disable_stop_requests(self):
    for kind in ('cancel', 'override', 'resume', 'disable'):
      with self.subTest(kind=kind):
        controller, _, send = load_controller()
        msgs = messages(target=55, cluster=35)
        run(controller, msgs)
        if kind == 'disable':
          msgs[1].enabled = False
        else:
          setattr(msgs[1].cruiseControl, kind, True)
        self.assertEqual(run(controller, msgs, count=1), send.none)

  def test_disabled_controller_does_not_request_speed(self):
    controller, _, send = load_controller()
    msgs = messages(target=55, cluster=35)
    msgs[1].enabled = False
    self.assertEqual(run(controller, msgs), send.none)

  def test_factory_minimum_blocks_further_decrease(self):
    controller, _, send = load_controller()
    self.assertEqual(run(controller, messages(target=10, cluster=20)), send.none)


if __name__ == '__main__':
  unittest.main()
