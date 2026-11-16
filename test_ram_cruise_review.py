"""Synthetic regression checks for the offline analyzer, not vehicle validation."""
import math
import unittest
from ram_cruise_review import MPH, analyze, plan_sample


def sample(t=0, **changes):
  value = dict(t=t, enabled=True, v_ego_mps=50*MPH, a_ego_mps2=0,
               requested_mps=50*MPH, cluster_set_mps=50*MPH,
               speed_limit_valid=True, source='cruise')
  value.update(changes)
  return value


def codes(rows):
  return [f['code'] for f in analyze(rows)['findings']]


class ReviewTests(unittest.TestCase):
  def test_curve_drop_and_actual_braking_are_separate(self):
    result = codes([sample(), sample(.5, requested_mps=30*MPH, source='sccVision', a_ego_mps2=-3)])
    self.assertIn('abrupt_target_drop', result)
    self.assertIn('rapid_deceleration', result)

  def test_gradual_target_change_does_not_flag_abrupt_drop(self):
    self.assertNotIn('abrupt_target_drop', codes([sample(i, requested_mps=(50-i)*MPH) for i in range(10)]))

  def test_missing_limit_increase_and_explicit_ceiling(self):
    result = codes([sample(requested_mps=35*MPH), sample(1, requested_mps=55*MPH,
      source='speedLimitAssist', speed_limit_valid=False, driver_ceiling_mps=35*MPH)])
    self.assertIn('target_above_driver_ceiling', result)
    self.assertIn('limit_assist_increase_without_current_limit', result)

  def test_unknown_ceiling_is_not_invented(self):
    report = analyze([sample(requested_mps=55*MPH)])
    self.assertEqual(report['driver_ceiling_samples'], 0)
    self.assertNotIn('target_above_driver_ceiling', codes([sample(requested_mps=55*MPH)]))

  def test_delayed_cluster_match_and_recovery(self):
    rows = [sample(i, requested_mps=35*MPH) for i in range(5)]
    rows += [sample(5, requested_mps=35*MPH, cluster_set_mps=35*MPH)]
    self.assertEqual(codes(rows).count('sustained_requested_cluster_gap'), 1)

  def test_sparse_data_does_not_claim_continuous_mismatch(self):
    result = codes([sample(0, requested_mps=35*MPH), sample(10, requested_mps=30*MPH)])
    self.assertIn('data_gap', result)
    self.assertNotIn('sustained_requested_cluster_gap', result)
    self.assertNotIn('abrupt_target_drop', result)

  def test_disabled_data_is_not_a_driving_event(self):
    self.assertEqual(codes([sample(enabled=False, a_ego_mps2=-4)]), [])

  def test_bad_units_nonfinite_and_timestamps_rejected(self):
    for bad in (sample(v_ego_mps=math.nan), sample(requested_mps=255), sample(t=-1), sample(enabled='true')):
      with self.assertRaises(ValueError):
        analyze([bad])
    with self.assertRaises(ValueError):
      analyze([sample(), sample()])

  def test_adapter_uses_actual_cluster_and_preserves_acceleration(self):
    value = plan_sample(0, {'vEgo':20, 'aEgo':-2, 'cruiseState':{'speedCluster':22}},
      {'enabled':True}, {'vTarget':15, 'aTarget':-.2, 'longitudinalPlanSource':'sccMap',
       'speedLimit':{'resolver':{'speedLimitValid':False, 'speedLimitLastValid':True}}})
    self.assertEqual(value['cluster_set_mps'], 22)
    self.assertEqual(value['planned_accel_mps2'], -.2)
    self.assertFalse(value['speed_limit_valid'])
    self.assertNotIn('driver_ceiling_mps', value)


if __name__ == '__main__':
  unittest.main()
