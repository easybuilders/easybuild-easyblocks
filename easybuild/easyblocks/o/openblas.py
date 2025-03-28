"""
EasyBuild support for building and installing OpenBLAS, implemented as an easyblock

@author: Andrew Edmondson (University of Birmingham)
@author: Alex Domingo (Vrije Universiteit Brussel)
@author: Kenneth Hoste (Ghent University)
"""
import os
import re
from easybuild.tools import LooseVersion
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import AARCH64, POWER, get_cpu_architecture, get_shared_lib_ext
from easybuild.tools.toolchain.compiler import OPTARCH_GENERIC
import easybuild.tools.environment as env

LAPACK_TEST_TARGET = 'lapack-test'
TARGET = 'TARGET'


class EB_OpenBLAS(ConfigureMake):
    """Support for building/installing OpenBLAS."""

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for OpenBLAS easyblock."""
        extra_vars = {
            'max_failing_lapack_tests_num_errors': [0, "Maximum number of LAPACK tests failing "
                                                    "due to numerical errors", CUSTOM],
            'max_failing_lapack_tests_other_errors': [0, "Maximum number of LAPACK tests failing "
                                                      "due to non-numerical errors", CUSTOM],
            'run_lapack_tests': [False, "Run LAPACK tests during test step, "
                                        "and check whether failing tests exceeds threshold", CUSTOM],
        }

        return ConfigureMake.extra_options(extra_vars)

    def configure_step(self):
        """ set up some options - but no configure command to run"""

        default_opts = {
            'BINARY': '64',
            'CC': os.getenv('CC'),
            'FC': os.getenv('FC'),
            'MAKE_NB_JOBS': '-1',  # Disable internal parallelism to let EB choose
            'USE_OPENMP': '1',
            'USE_THREAD': '1',
        }

        if '%s=' % TARGET in self.cfg['buildopts']:
            # Add any TARGET in buildopts to default_opts, so it is passed to testopts and installopts
            for buildopt in self.cfg['buildopts'].split():
                optpair = buildopt.split('=')
                if optpair[0] == TARGET:
                    default_opts[optpair[0]] = optpair[1]
        elif LooseVersion(self.version) < LooseVersion('0.3.6') and get_cpu_architecture() == POWER:
            # There doesn't seem to be a POWER9 option yet, but POWER8 should work.
            print_warning("OpenBLAS 0.3.5 and lower have known issues on POWER systems")
            default_opts[TARGET] = 'POWER8'

        # special care must be taken when performing a generic build of OpenBLAS
        if build_option('optarch') == OPTARCH_GENERIC:
            default_opts['DYNAMIC_ARCH'] = '1'

            if get_cpu_architecture() == AARCH64:
                # when building for aarch64/generic, we also need to set TARGET=ARMV8 to make sure
                # that the driver parts of OpenBLAS are compiled generically;
                # see also https://github.com/OpenMathLib/OpenBLAS/issues/4945
                default_opts[TARGET] = 'ARMV8'

                # use -mtune=generic rather than -mcpu=generic in $CFLAGS for aarch64/generic,
                # because -mcpu=generic implies a particular -march=armv* which clashes with those used by OpenBLAS
                # when building with DYNAMIC_ARCH=1
                cflags = os.getenv('CFLAGS').replace('-mcpu=generic', '-mtune=generic')
                self.log.info("Replaced -mcpu=generic with -mtune=generic in $CFLAGS")
                env.setvar('CFLAGS', cflags)

        for key in sorted(default_opts.keys()):
            for opts_key in ['buildopts', 'testopts', 'installopts']:
                if '%s=' % key not in self.cfg[opts_key]:
                    self.cfg.update(opts_key, "%s='%s'" % (key, default_opts[key]))

        self.cfg.update('installopts', 'PREFIX=%s' % self.installdir)

    def build_step(self):
        """ Custom build step excluding the tests """

        # Equivalent to `make all` without the tests
        build_parts = []
        if LooseVersion(self.version) < LooseVersion('0.3.23'):
            build_parts += ['libs', 'netlib']
            for buildopt in self.cfg['buildopts'].split():
                if 'BUILD_RELAPACK' in buildopt and '1' in buildopt:
                    build_parts += ['re_lapack']
        # just shared is necessary and sufficient with 0.3.23 + xianyi/OpenBLAS#3983
        build_parts += ['shared']

        # Pass CFLAGS through command line to avoid redefinitions (issue xianyi/OpenBLAS#818)
        cflags = 'CFLAGS'
        if os.environ[cflags]:
            self.cfg.update('buildopts', "%s='%s'" % (cflags, os.environ[cflags]))
            del os.environ[cflags]
            self.log.info("Environment variable %s unset and passed through command line" % cflags)

        makecmd = f'make {self.parallel_flag}'

        cmd = ' '.join([self.cfg['prebuildopts'], makecmd, ' '.join(build_parts), self.cfg['buildopts']])
        run_shell_cmd(cmd)

    def check_lapack_test_results(self, test_output):
        """Check output of OpenBLAS' LAPACK test suite ('make lapack-test')."""

        # example:
        #                         -->   LAPACK TESTING SUMMARY  <--
        # SUMMARY                 nb test run     numerical error         other error
        # ================        ===========     =================       ================
        # ...
        # --> ALL PRECISIONS      4116982         4172    (0.101%)        0       (0.000%)
        test_summary_pattern = r'\s+'.join([
            r"^--> ALL PRECISIONS",
            r"(?P<test_cnt>[0-9]+)",
            r"(?P<test_fail_num_error>[0-9]+)\s+\([0-9.]+\%\)",
            r"(?P<test_fail_other_error>[0-9]+)\s+\([0-9.]+\%\)",
        ])
        regex = re.compile(test_summary_pattern, re.M)
        res = regex.search(test_output)
        if res:
            (tot_cnt, fail_cnt_num_errors, fail_cnt_other_errors) = [int(x) for x in res.groups()]
            msg = "%d LAPACK tests run - %d failed due to numerical errors - %d failed due to other errors"
            self.log.info(msg, tot_cnt, fail_cnt_num_errors, fail_cnt_other_errors)

            if fail_cnt_other_errors > self.cfg['max_failing_lapack_tests_other_errors']:
                raise EasyBuildError("Too many LAPACK tests failed due to non-numerical errors: %d (> %d)",
                                     fail_cnt_other_errors, self.cfg['max_failing_lapack_tests_other_errors'])

            if fail_cnt_num_errors > self.cfg['max_failing_lapack_tests_num_errors']:
                raise EasyBuildError("Too many LAPACK tests failed due to numerical errors: %d (> %d)",
                                     fail_cnt_num_errors, self.cfg['max_failing_lapack_tests_num_errors'])
        else:
            raise EasyBuildError("Failed to find test summary using pattern '%s' in test output: %s",
                                 test_summary_pattern, test_output)

    def test_step(self):
        """ Mandatory test step plus optional runtest"""

        run_tests = ['tests']

        if self.cfg['run_lapack_tests']:
            run_tests += [LAPACK_TEST_TARGET]

        if self.cfg['runtest']:
            run_tests += [self.cfg['runtest']]

        for runtest in run_tests:
            cmd = "%s make %s %s" % (self.cfg['pretestopts'], runtest, self.cfg['testopts'])
            res = run_shell_cmd(cmd)

            # Raise an error if any test failed
            regex = re.compile("FATAL ERROR", re.M)
            errors = regex.findall(res.output)
            if errors:
                raise EasyBuildError("Found %d fatal errors in test output!", len(errors))

            # check number of failing LAPACK tests more closely
            if runtest == LAPACK_TEST_TARGET:
                self.check_lapack_test_results(res.output)

    def sanity_check_step(self):
        """ Custom sanity check for OpenBLAS """
        custom_paths = {
            'files': ['include/cblas.h', 'include/f77blas.h', 'include/lapacke_config.h', 'include/lapacke.h',
                      'include/lapacke_mangling.h', 'include/lapacke_utils.h', 'include/openblas_config.h',
                      'lib/libopenblas.a', 'lib/libopenblas.%s' % get_shared_lib_ext()],
            'dirs': [],
        }
        super(EB_OpenBLAS, self).sanity_check_step(custom_paths=custom_paths)
