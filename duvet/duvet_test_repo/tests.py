import unittest

import fakelib

class ExampleTestCase(unittest.TestCase):
    def test_that_never_changes(self):
        self.assertFalse(fakelib.noop())

    def test_that_will_be_changed_outside(self):
        self.assertEqual(fakelib.do_something(0), 1)

    def test_that_will_be_changed_inside(self):
        self.assertEqual(1+bool(fakelib.noop()), 1)
