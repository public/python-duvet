from __future__ import absolute_import

import json
import logging
import os
import re
import sys
import shelve


from nose.plugins.base import Plugin
from nose.util import src, tolist

log = logging.getLogger(__name__)

try:
    import coverage
    if not hasattr(coverage, 'coverage'):
        raise ImportError("Unable to import coverage module")
except ImportError:
    coverage = None
    log.error("Coverage not available: unable to import coverage module")

try:
    import git
except ImportError:
    git = None
    log.error("Git not available: unable to import module")


class DuvetCover(Plugin):
    score = 200
    status = {}
    gitCommit = None
    shelf = None

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
                          default=env.get('NOSE_DUVET_ERASE', False),
                          dest="duvet_erase",
                          help="Erase previously collected coverage "
                          "statistics before run")

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
        log.debug("Coverage begin")
        self.skipModules = sys.modules.copy()

        # work out git position
        test_repo = git.Repo('.')
        self.gitCommit = (
            None if test_repo.is_dirty()
            else test_repo.head.commit.hexsha
        )

        if self.options.duvet_erase:
            # remove the existing coverage shelf
            try:
                os.remove('.duvet')
            except OSError:
                pass

        self.shelf = shelve.open('.duvet')
        if not self.gitCommit in self.shelf:
            self.shelf[self.gitCommit] = []

    def beforeTest(self, test):
        """
        Setup a coverage instance just for this test.
        """

        self.shelf[self._test_key(test)] = None
        self.shelf[self.gitCommit].append(test.address())

        test.coverage = coverage.coverage(
            auto_data=False,
            data_suffix=None
        )

        test.coverage.erase()
        test.coverage.start()

    def stopTest(self, test):
        """
        Stop the coverage collection before recording it
        """
        test.coverage.stop()

    def addFailure(self, test, exc):
        self.shelf[self._test_key(test)] = False

    def addError(self, test, exc):
        self.shelf[self._test_key(test)] = False

    def addSuccess(self, test):
        cover_key = self._test_key(test)
        cover_data = self.get_coverage_data(test.coverage)
        self.shelf[cover_key] = cover_data

    def afterTest(self, test):
        self.shelf.sync()

    def report(self, stream):
        shelf = shelve.open('.duvet')
        print >>stream, "COVERAGE"
        for k in shelf:
            print >>stream, k

    def _test_key(self, test):
        return json.dumps([self.gitCommit] + list(test.address()))

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



