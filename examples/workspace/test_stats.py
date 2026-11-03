import unittest

from stats import mean, median


class StatsTests(unittest.TestCase):
    def test_mean(self):
        self.assertEqual(mean([2, 4, 6]), 4)

    def test_mean_rejects_empty_input(self):
        with self.assertRaises(ValueError):
            mean([])

    def test_median_odd(self):
        self.assertEqual(median([9, 1, 5]), 5)

    def test_median_even(self):
        self.assertEqual(median([1, 3, 5, 9]), 4)

    def test_median_rejects_empty_input(self):
        with self.assertRaises(ValueError):
            median([])


if __name__ == "__main__":
    unittest.main()

