"""
EasyBuild support for building and installing OpenBLAS, implemented as an easyblock

@author: Andrew Edmondson (University of Birmingham)
@author: Alex Domingo (Vrije Universiteit Brussel)
@author: Jasper Grimm (University of York)
@author: Kenneth Hoste (Ghent University)
"""
import os
import re
from easybuild.tools import LooseVersion
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.filetools import apply_regex_substitutions
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
            'enable_ilp64': [True, "Also build OpenBLAS with 64-bit integer support", CUSTOM],
            'ilp64_lib_suffix': ['64', "Library name suffix to use when building with 64-bit integers", CUSTOM],
            'ilp64_symbol_suffix': ['64_', "Symbol suffix to use when building with 64-bit integers", CUSTOM],
            'max_failing_lapack_tests_num_errors': [0, "Maximum number of LAPACK tests failing "
                                                    "due to numerical errors", CUSTOM],
            'max_failing_lapack_tests_other_errors': [0, "Maximum number of LAPACK tests failing "
                                                      "due to non-numerical errors", CUSTOM],
            'run_lapack_tests': [False, "Run LAPACK tests during test step, "
                                        "and check whether failing tests exceeds threshold", CUSTOM],
        }

        return ConfigureMake.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """ Ensure iterative build if also building with 64-bit integer support """
        super(EB_OpenBLAS, self).__init__(*args, **kwargs)

        if self.cfg['enable_ilp64']:
            if not isinstance(self.cfg['buildopts'], list):
                niter = 1 + sum([bool(self.cfg[x]) for x in ['ilp64_lib_suffix', 'ilp64_symbol_suffix']])
                # ensure iterative build by duplicating buildopts
                self.cfg['buildopts'] = [self.cfg['buildopts']] * niter
            else:
                print_warning("buildopts cannot be a list when 'enable_ilp64' is enabled; ignoring 'enable_ilp64'")
                self.cfg['enable_ilp64'] = False

        self.orig_opts = {
            'buildopts': '',
            'testopts': '',
            'installopts': '',
        }

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

        ilp64_lib_opts = {
            'INTERFACE64': '1',
            'LIBPREFIX': f"libopenblas{self.cfg['ilp64_lib_suffix']}",
        }
        ilp64_symbol_opts = {
            'INTERFACE64': '1',
            'SYMBOLSUFFIX': self.cfg['ilp64_symbol_suffix'],
        }

        # ensure build/test/install options don't persist between iterations
        if self.cfg['enable_ilp64']:
            if self.iter_idx > 0:
                # reset to original build/test/install options
                for key in self.orig_opts.keys():
                    self.cfg[key] = self.orig_opts[key]
            else:
                # store original options
                for key in self.orig_opts.keys():
                    self.orig_opts[key] = self.cfg[key]

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

        all_opts = default_opts.copy()
        if self.iter_idx > 0 and self.cfg['enable_ilp64']:
            # update build/test/install options for ILP64
            if self.cfg['ilp64_lib_suffix'] and self.cfg['ilp64_symbol_suffix']:
                if self.iter_idx == 1:
                    all_opts.update(ilp64_lib_opts)
                else:
                    all_opts.update(ilp64_symbol_opts)
            elif self.cfg['ilp64_lib_suffix']:
                all_opts.update(ilp64_lib_opts)
            elif self.cfg['ilp64_symbol_suffix']:
                all_opts.update(ilp64_symbol_opts)

        for key in sorted(all_opts.keys()):
            for opts_key in ['buildopts', 'testopts', 'installopts']:
                if f'{key}=' not in self.cfg[opts_key]:
                    self.cfg.update(opts_key, f"{key}='{all_opts[key]}'")

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
            self.cfg.update('buildopts', f"{cflags}='{os.environ[cflags]}'")
            del os.environ[cflags]
            self.log.info(f"Environment variable {cflags} unset and passed through command line")

        makecmd = f'make {self.parallel_flag}'

        cmd = ' '.join([self.cfg['prebuildopts'], makecmd, ' '.join(build_parts), self.cfg['buildopts']])
        run_shell_cmd(cmd)

    def install_step(self):
        """Fix libsuffix in openblas64.pc if it exists"""
        super(EB_OpenBLAS, self).install_step()
        if self.iter_idx > 0 and self.cfg['enable_ilp64'] and self.cfg['ilp64_lib_suffix']:
            filepath = os.path.join(self.installdir, 'lib', 'pkgconfig', 'openblas64.pc')
            if os.path.exists(filepath):
                regex_subs = [
                    (r'^libsuffix=.*$', f"libsuffix={self.cfg['ilp64_lib_suffix']}"),
                    (r'^Name: openblas$', 'Name: openblas64'),
                ]
                apply_regex_substitutions(filepath, regex_subs, backup=False)

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
            cmd = f"{self.cfg['pretestopts']} make {runtest} {self.cfg['testopts']}"
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
        shlib_ext = get_shared_lib_ext()
        custom_paths = {
            'files': ['include/cblas.h', 'include/f77blas.h', 'include/lapacke_config.h', 'include/lapacke.h',
                      'include/lapacke_mangling.h', 'include/lapacke_utils.h', 'include/openblas_config.h',
                      'lib/libopenblas.a', f'lib/libopenblas.{shlib_ext}'],
            'dirs': [],
        }
        if self.cfg['enable_ilp64']:
            for suffixtype in 'lib', 'symbol':
                filename_suffix = self.cfg[f'ilp64_{suffixtype}_suffix']
                if filename_suffix:
                    custom_paths['files'].extend(f"lib/libopenblas{filename_suffix}.{ext}"
                                                 for ext in ['a', shlib_ext])

        super().sanity_check_step(custom_paths=custom_paths)
