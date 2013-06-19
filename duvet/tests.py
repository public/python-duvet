from __future__ import absolute_import

import shutil
import sys
import subprocess
import tarfile
import tempfile
import os.path
import unittest

import git
import xunitparser


class TestDuvet(unittest.TestCase):
    repo_tar = "duvet_test_repo.tar.gz"

    def setUp(self):
        self._original_path = os.getcwd()

        self.repo_root = tempfile.mkdtemp(prefix="tmp_duvet_test_repo_")
        self.repo_path = os.path.join(self.repo_root, "duvet_test_repo")

        tarfile.open(self.repo_tar, "r:gz").extractall(self.repo_root)
        self.repo = git.Repo(self.repo_path)

        os.chdir(self.repo_path)

    def tearDown(self):
        os.chdir(self._original_path)
        shutil.rmtree(self.repo_root)

    def run_repo_suite(self):
        subprocess.check_call(["nosetests", "--with-xunit", "--with-duvetcover", "--duvet-skip"])
        result = xunitparser.parse(open("nosetests.xml"))
        return sum(1 for tc in result[0] if tc.good)

    def test_unchanged(self):
        self.repo.git.checkout("A")

        ran_A = self.run_repo_suite()

        self.repo.git.checkout("B")
        self.repo.git.reset("A")

        ran_AB = self.run_repo_suite()

        self.assertEqual(ran_AB, 0)

    def test_mod_outside_test(self):
        self.repo.git.checkout("B")

        ran_B = self.run_repo_suite()

        self.repo.git.checkout("C")
        self.repo.git.reset("B")

        ran_BC = self.run_repo_suite()

        self.assertEqual(ran_BC, 1)

    def test_mod_inside_test(self):
        self.repo.git.checkout("C")

        ran_C = self.run_repo_suite()

        self.repo.git.checkout("D")
        self.repo.git.reset("C")

        ran_CD = self.run_repo_suite()

        self.assertEqual(ran_CD, 1)
