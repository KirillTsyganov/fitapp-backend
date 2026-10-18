"""Run from backend/: python -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from coach import prompts, rules  # noqa: E402  (importing coach also puts api/ on sys.path)
from schemas import CoachWorkoutResponse, ExerciseItem, WorkoutBlock  # noqa: E402


def ex(name, sets=1, allocated=40, rest=20, **kw):
    return ExerciseItem(
        name=name, modality='calisthenics', target_pattern='push', sets=sets,
        reps_or_duration='10 reps', allocated_seconds=allocated, rpe=6, rest_seconds=rest, **kw,
    )


def flow(blocks):
    return CoachWorkoutResponse(
        flow_name='t', estimated_total_minutes=0, target_focus='t', message='m',
        diagnostic_needed=False, blocks=blocks,
    )


class TimelineTests(unittest.TestCase):
    def test_few_shot_example_passes_its_own_rules(self):
        example = prompts._EXAMPLE
        self.assertEqual(rules.validate_flow(example, 20), [])
        self.assertEqual(round(rules.total_seconds(example) / 60), example.estimated_total_minutes)

    def test_linear_total(self):
        # A: 2x40 + 1 rest(20) between sets, then rest(20)+5 buffer; B: 40 only (last set, no rest).
        r = flow([WorkoutBlock(block_name='Primary Skill / Strength', structure='linear',
                               exercises=[ex('A', sets=2), ex('B', sets=1)])])
        self.assertEqual(rules.total_seconds(r), 40 + 20 + 40 + 20 + 5 + 40)

    def test_circuit_cycles_rounds_and_buffers_every_station(self):
        r = flow([WorkoutBlock(block_name='Primary Skill / Strength', structure='circuit',
                               exercises=[ex('A', sets=2), ex('B', sets=2)])])
        self.assertEqual([e.name for e in rules.station_sequence(r)], ['A', 'B', 'A', 'B'])
        self.assertEqual(rules.total_seconds(r), 4 * 40 + 3 * (20 + 5))

    def test_blocks_play_in_canonical_order(self):
        r = flow([
            WorkoutBlock(block_name='Down-Regulation / Cool Down', exercises=[ex('Z', rest=None)]),
            WorkoutBlock(block_name='Prep / Dynamic Flow', exercises=[ex('P')]),
        ])
        self.assertEqual([e.name for e in rules.station_sequence(r)], ['P', 'Z'])


class ValidationTests(unittest.TestCase):
    def test_missing_allocated_seconds_is_rejected(self):
        r = flow([WorkoutBlock(block_name='Prep / Dynamic Flow', exercises=[ex('A', allocated=None, rest=None)])])
        self.assertTrue(any('allocated_seconds' in v for v in rules.validate_workout(r)))

    def test_time_outside_tolerance_is_rejected(self):
        r = flow([WorkoutBlock(block_name='Prep / Dynamic Flow', exercises=[ex('A', sets=3)])])
        self.assertTrue(any('Computed session time' in v for v in rules.validate_flow(r, 20)))

    def test_time_within_tolerance_is_accepted(self):
        # 8 sets x 60s work + 7 rests x 90s = 1110s, within 120s of an 18-minute target.
        r = flow([WorkoutBlock(block_name='Prep / Dynamic Flow', exercises=[ex('A', sets=8, allocated=60, rest=90)])])
        self.assertEqual(rules.total_seconds(r), 8 * 60 + 7 * 90)
        self.assertEqual(rules.validate_flow(r, 18), [])

    def test_only_the_final_exercise_may_omit_rest(self):
        r = flow([WorkoutBlock(block_name='Prep / Dynamic Flow', exercises=[ex('A', rest=None), ex('B', rest=None)])])
        names = [v for v in rules.validate_flow(r, 1) if 'rest_seconds is required' in v]
        self.assertEqual(len(names), 1)
        self.assertIn("'A'", names[0])

    def test_circuit_requires_matching_rounds(self):
        r = flow([WorkoutBlock(block_name='Primary Skill / Strength', structure='circuit',
                               exercises=[ex('A', sets=2), ex('B', sets=3)])])
        self.assertTrue(any('same sets' in v for v in rules.validate_workout(r)))

    def test_legacy_flow_without_new_fields_still_parses(self):
        legacy = {'name': 'x', 'modality': 'yoga', 'target_pattern': 'p', 'sets': 1, 'reps_or_duration': '30s hold'}
        self.assertIsNone(ExerciseItem(**legacy).allocated_seconds)


if __name__ == '__main__':
    unittest.main()
