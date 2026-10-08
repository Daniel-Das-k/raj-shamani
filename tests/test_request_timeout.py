from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from knowledge.request_timeout import AnswerTimeout, answer_deadline, remaining_timeout


class RequestTimeoutTests(unittest.TestCase):
    def test_sequential_calls_share_remaining_time_and_cleanup_restores_default(self):
        with patch('knowledge.request_timeout.time.monotonic', return_value=100) as clock:
            with answer_deadline(20):
                self.assertEqual(remaining_timeout(120), 20)
                clock.return_value = 115
                self.assertEqual(remaining_timeout(120), 5)
                clock.return_value = 120
                with self.assertRaises(AnswerTimeout):
                    remaining_timeout(120)
            self.assertEqual(remaining_timeout(120), 120)

    def test_nested_budget_cannot_extend_parent_and_restores_on_error(self):
        with patch('knowledge.request_timeout.time.monotonic', return_value=100):
            with answer_deadline(20):
                with answer_deadline(100):
                    self.assertEqual(remaining_timeout(120), 20)
                with self.assertRaises(RuntimeError):
                    with answer_deadline(5):
                        self.assertEqual(remaining_timeout(120), 5)
                        raise RuntimeError('failure')
                self.assertEqual(remaining_timeout(120), 20)

    def test_one_request_cannot_change_another_threads_budget(self):
        with patch('knowledge.request_timeout.time.monotonic', return_value=100):
            with answer_deadline(5), ThreadPoolExecutor(max_workers=1) as pool:
                self.assertEqual(pool.submit(remaining_timeout, 120).result(), 120)
                self.assertEqual(remaining_timeout(120), 5)
