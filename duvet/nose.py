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


class DuvetCover(Plugin):
    coverMinPercentage = None

    score = 200
    status = {}

    def options(self, parser, env):
        """
        Add options to command line.
        """
        super(DuvetCover, self).options(parser, env)
        parser.add_option("--duvet-package", action="append",
                          default=env.get('NOSE_COVER_PACKAGE'),
                          metavar="PACKAGE",
                          dest="cover_packages",
                          help="Restrict coverage output to selected packages "
                          "[NOSE_COVER_PACKAGE]")
        parser.add_option("--duvet-erase", action="store_true",
                          default=env.get('NOSE_COVER_ERASE'),
                          dest="cover_erase",
                          help="Erase previously collected coverage "
                          "statistics before run")
        parser.add_option("--duvet-tests", action="store_true",
                          dest="cover_tests",
                          default=env.get('NOSE_COVER_TESTS'),
                          help="Include test modules in coverage report "
                          "[NOSE_COVER_TESTS]")
        parser.add_option("--duvet-inclusive", action="store_true",
                          dest="cover_inclusive",
                          default=env.get('NOSE_COVER_INCLUSIVE'),
                          help="Include all python files under working "
                          "directory in coverage report.  Useful for "
                          "discovering holes in test coverage if not all "
                          "files are imported by the test suite. "
                          "[NOSE_COVER_INCLUSIVE]")
        parser.add_option("--duvet-html", action="store_true",
                          default=env.get('NOSE_COVER_HTML'),
                          dest='cover_html',
                          help="Produce HTML coverage information")
        parser.add_option('--duvet-html-dir', action='store',
                          default=env.get('NOSE_COVER_HTML_DIR', 'cover'),
                          dest='cover_html_dir',
                          metavar='DIR',
                          help='Produce HTML coverage information in dir')
        parser.add_option("--duvet-branches", action="store_true",
                          default=env.get('NOSE_COVER_BRANCHES'),
                          dest="cover_branches",
                          help="Include branch coverage in coverage report "
                          "[NOSE_COVER_BRANCHES]")

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

        self.enabled = bool(coverage)

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

        if options.cover_html:
            log.debug('Will put HTML coverage report in %s', options.cover_html_dir)

        if self.enabled:
            self.status['active'] = True

    def begin(self):
        """
        Begin recording coverage information.
        """
        log.debug("Coverage begin")
        self.skipModules = sys.modules.copy()

        # remove the existing coverage shelf
        try:
            os.remove('.duvet')
        except OSError:
            pass

        # setup the coverage instance for tracking everything else
        self.globalCoverage = coverage.coverage(
            auto_data=False,
            branch=self.options.cover_branches,
            data_suffix=None
        )
        self.globalCoverage.exclude('#pragma[: ]+[nN][oO] [cC][oO][vV][eE][rR]')
        self.globalCoverage.erase()
        self.globalCoverage.load()
        self.globalCoverage.start()

    def beforeTest(self, test):
        """
        Setup a coverage instance just for this test.
        """
        test.coverage = coverage.coverage(
            auto_data=False,
            branch=self.options.cover_branches,
            data_suffix=None
        )

        test.coverage.exclude('#pragma[: ]+[nN][oO] [cC][oO][vV][eE][rR]')
        test.coverage.erase()
        test.coverage.load()
        test.coverage.start()

    def afterTest(self, test):
        """
        Collect the coverage data from this test and shelve them.
        """

        test.coverage.stop()

        cover_data = self.get_coverage_data(test.coverage)

        shelf = shelve.open('.duvet')
        shelf[json.dumps(test.address())] = cover_data
        shelf.close()


    def report(self, stream):
        self.globalCoverage.stop()
        cover_data = self.get_coverage_data(self.globalCoverage)

        print >>stream, cover_data

        shelf = shelve.open('.duvet')
        print >>stream, "COVERAGE"
        for k in shelf:
            print >>stream, k, shelf[k]

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
                    and (self.options.cover_tests
                         or not self.conf.testMatch.search(name))
                ):
                    log.debug("coverage for %s", name)
                    return True

        if name in self.skipModules:
            log.debug("no coverage for %s: loaded before coverage start",
                      name)
            return False

        if self.conf.testMatch.search(name) and not self.options.cover_tests:
            log.debug("no coverage for %s: is a test", name)
            return False

        # accept any package that passed the previous tests, unless
        # coverPackages is on -- in that case, if we wanted this
        # module, we would have already returned True
        return not self.coverPackages

    def wantFile(self, file, package=None):
        """If inclusive coverage enabled, return true for all source files
        in wanted packages.
        """
        if self.options.cover_inclusive:
            if file.endswith(".py"):
                if package and self.coverPackages:
                    for want in self.coverPackages:
                        if package.startswith(want):
                            return True
                else:
                    return True
        return None


