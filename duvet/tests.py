from __future__ import absolute_import

import unittest

import duvet.nose

def test_derp():
    x = duvet.nose.DuvetCover()
    for i in range(10):
        y = i * i

def noexec():
    x = 1 + 1
    y = len(sys.modules)
    return x * y
