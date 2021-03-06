from __future__ import absolute_import

from cStringIO import StringIO
import functools
import json
import logging
import os
import os.path
import re
import sys
import shelve

from nose.plugins.errorclass import ErrorClass, ErrorClassPlugin
from nose.plugins.skip import SkipTest
from nose.suite import ContextSuite
from nose.util import src, tolist

log = logging.getLogger(__name__)

from bzrlib import patiencediff
import coverage
import git


def difflines(a, b):
    """
    Generator of the the indexes where changes occured in a sequence
    """
    matcher = patiencediff.PatienceSequenceMatcher
    for groups in matcher(None, a, b).get_grouped_opcodes(0):
        for group in groups:
            for i in xrange(group[1], group[2]+1):
                yield i


def iter_suite(suite):
    """
    Stolen from django-nose.

    This triggers on anything that inherits from unittest.TestCase because
    of NOP setUpClass etc functions.
    """
    if (
        not hasattr(suite, '_tests') or
        (hasattr(suite, 'hasFixtures') and suite.hasFixtures())
    ) and hasattr(suite, 'address'):
        # We hit a Test or something with setup, so do the thing. (Note that
        # "fixtures" here means setup or teardown routines, not Django
        # fixtures.)
        yield suite
    else:
        for s in suite._tests:
            for t in iter_suite(s):
                yield t


class DuvetSkipTest(Exception):
    pass


class DuvetCover(ErrorClassPlugin):
    enabled = True
    score = 200
    status = {}
    gitCommit = None
    shelf = None
    duvet_skipped = ErrorClass(
        DuvetSkipTest,
        label="DUVET",
        isfailure=False
    )

    def options(self, parser, env):
        """
        Add options to command line.
        """
        super(DuvetCover, self).options(parser, env)
        parser.add_option("--duvet-package", action="append",
                          default=env.get('NOSE_DUVET_PACKAGE'),
                          metavar="PACKAGE",
                          dest="cover_packages",
                          help="Restrict coverage output to selected packages "
                          "[NOSE_DUVET_PACKAGE]")
        parser.add_option("--duvet-erase", action="store_true",
                          default=bool(env.get('NOSE_DUVET_ERASE', False)),
                          dest="duvet_erase",
                          help="Erase previously collected coverage "
                          "statistics before run")
        parser.add_option("--duvet-skip", action="store_true",
                          default=bool(env.get('NOSE_DUVET_SKIP', False)),
                          metavar="PACKAGE",
                          dest="skip",
                          help=("Skip tests that don't appear to have been"
                                "effected by changes")
                          )
        parser.add_option("--duvet-sort", action="store_true",
                          default=bool(env.get('NOSE_DUVET_SORT', False)),
                          metavar="PACKAGE",
                          dest="sort",
                          help=("Sort the tests so that changed ones are run"
                                "first")
                          )

    def configure(self, options, conf):
        """
        Configure plugin.
        """
        try:
            self.status.pop('active')
        except KeyError:
            pass

        super(DuvetCover, self).configure(options, conf)

        if conf.worker:
            return

        self.enabled = bool(coverage) and bool(git)

        self.conf = conf
        self.options = options

        self.coverPackages = []
        if options.cover_packages:
            if isinstance(options.cover_packages, (list, tuple)):
                cover_packages = options.cover_packages
            else:
                cover_packages = [options.cover_packages]
            for pkgs in [tolist(x) for x in cover_packages]:
                self.coverPackages.extend(pkgs)

        if self.coverPackages:
            log.info("Coverage report will include only packages: %s",
                     self.coverPackages)

        if self.enabled:
            self.status['active'] = True

    def begin(self):
        """
        Begin recording coverage information.
        """
        self.skipModules = sys.modules.copy()

        # work out git position
        self.gitRepo = git.Repo('.')
        self.gitCommit = (
            None if self.gitRepo.is_dirty()
            else self.gitRepo.head.commit.hexsha
        )

        # sort out the shelf to store our data in
        self.duvetPath = os.path.join(self.gitRepo.working_dir, '.duvet')

        if self.options.duvet_erase:
            # remove the existing coverage shelf
            try:
                os.remove(self.duvetPath)
            except OSError:
                pass

        self.shelf = shelve.open(self.duvetPath)
        if not self.gitCommit in self.shelf:
            self.shelf[self.gitCommit] = set()

    def _modified_test(self, test):
        """
        Scans the repo history and stored coverage data to try and work out
        if the tested code has been modified.

        Module scope changes won't be detected by this because we don't compute
        a graph of the name resolution within each test. This means code that
        uses dynamic imports may not get detected properly. It also means if
        you import the same name from a different module (e.g. simplejson vs json,
        cStringIO vs StringIO etc) the test will not be detected as changed.

        The current work-around for this is to use --duvet-sort instead of
        --duvet-skip.
        """
        try:
            return bool(test.duvet_modifications)
        except AttributeError:
            pass

        # find most recent data we can on this test
        history = self.gitRepo.iter_commits(self.gitCommit)
        old_coverage = None
        old_commit = None
        modified_execs = set()

        # dont bother looking if theres no data
        if not self.shelf:
            return True

        for commit in history:
            if test.address() in self.shelf.get(commit.hexsha, []):
                old_coverage = (
                    self.shelf[self._test_key(test, commit.hexsha)]
                )
                old_commit = commit
                break

        # test must be new!
        if not old_coverage:
            return True

        # map the raw coverage by filename
        file_covers = {cover[0]: (mod, cover)
                       for mod, cover in old_coverage.iteritems()}

        # now find the diff between the WC and the last tested commit
        diffs = old_commit.diff(None)
        for diff in diffs:
            a_stream = StringIO()
            diff.a_blob.stream_data(a_stream)

            a_data = a_stream.getvalue().splitlines()
            b_data = open(diff.b_blob.abspath).read().splitlines()
            diff_lines = set(difflines(a_data, b_data))

            try:
                cover = file_covers[os.path.join(self.gitRepo.working_dir,
                                                 diff.a_blob.path)][1]
            except KeyError:
                # diff is for a file with no coverage
                continue

            executed_lines = set(cover[1]) - set(cover[3])
            modified_execs = executed_lines & diff_lines
            test.duvet_modifications = modified_execs

        return bool(modified_execs)

    def prepareTest(self, test):
        if self.options.sort:
            tests = sorted(
                iter_suite(test),
                key=lambda t: (not self._modified_test(t), t.address())
            )
            return ContextSuite(tests)

    def beforeTest(self, test):
        """
        Setup a coverage instance just for this test.
        """
        if (
            self.options.skip and
            not self._modified_test(test)
        ):
            @functools.wraps(getattr(test.test, test.test._testMethodName))
            def skip(*args, **kwargs):
                raise DuvetSkipTest(test)
            setattr(test.test, test.test._testMethodName, skip)

        test.coverage = coverage.coverage(
            data_file=".coverage_%s" % id(test.test),
        )

        test.coverage.erase()
        test.coverage.start()

    def stopTest(self, test):
        """
        Stop the test coverage collection before recording it
        """
        test.coverage.stop()

    def addSuccess(self, test):
        cover_key = self._test_key(test)
        cover_data = self.get_coverage_data(test.coverage)

        test.coverage.erase()

        self.shelf[cover_key] = cover_data
        self.shelf[self.gitCommit] = (
            self.shelf[self.gitCommit] | set([test.address()])
        )

    def afterTest(self, test):
        self.shelf.sync()

    def report(self, stream):
        shelf = self.shelf

        print >>stream, "COVERAGE"
        for k in shelf:
            print >>stream, k, type(shelf[k])
            try:
                for m, c in shelf[k].iteritems():
                    if len(c[1]) != len(c[3]):
                        print >>stream, "\t", c[0], set(c[1]) - set(c[3])
            except AttributeError:
                print >>stream, "\t", shelf[k]


    def _global_key(self, commit=None):
        return json.dumps([commit or self.gitCommit, '__coverage__global__'])

    def _test_key(self, test, commit=None):
        return json.dumps([commit or self.gitCommit] + list(test.address()))

    def get_coverage_data(self, coverage_instance):
        # find modules imported during tests
        modules = [module for name, module in sys.modules.items()
                   if self.wantModuleCoverage(name, module)]
        # now extract data from coverage.py and shelve it
        return {mod.__name__: coverage_instance.analysis2(mod)
                for mod in modules}

    def wantModuleCoverage(self, name, module):
        if not hasattr(module, '__file__'):
            log.debug("no coverage of %s: no __file__", name)
            return False

        module_file = src(module.__file__)
        if not module_file or not module_file.endswith('.py'):
            log.debug("no coverage of %s: not a python file", name)
            return False

        if self.coverPackages:
            for package in self.coverPackages:
                if (
                    re.findall(r'^%s\b' % re.escape(package), name)
                ):
                    log.debug("coverage for %s", name)
                    return True

        if name in self.skipModules:
            log.debug("no coverage for %s: loaded before coverage start",
                      name)
            return False

        # accept any package that passed the previous tests, unless
        # coverPackages is on -- in that case, if we wanted this
        # module, we would have already returned True
        return not self.coverPackages
