##
# Copyright 2020-2024 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##
"""
EasyBuild support for building and installing PyTorch, implemented as an easyblock

@author: Alexander Grund (TU Dresden)
"""

import os
import re
import sys
import tempfile
import easybuild.tools.environment as env
from easybuild.tools import LooseVersion
from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.filetools import apply_regex_substitutions, mkdir, symlink
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.systemtools import POWER, get_cpu_architecture


if sys.version_info >= (3, 9):
    from typing import NamedTuple
    FailedTestNames = NamedTuple('FailedTestNames', [('error', list[str]), ('fail', list[str])])
    TestSuiteResult = NamedTuple('TestSuiteResult', [('name', str), ('summary', str)])
    TestResult = NamedTuple('TestResult', [('test_cnt', int),
                                           ('error_cnt', int),
                                           ('failure_cnt', int),
                                           ('failed_suites', list[TestSuiteResult])])
else:
    from collections import namedtuple
    FailedTestNames = namedtuple('FailedTestNames', ('error', 'fail'))
    TestSuiteResult = namedtuple('TestSuiteResult', ('name', 'summary'))
    TestResult = namedtuple('TestResult', ('test_cnt', 'error_cnt', 'failure_cnt', 'failed_suites'))


def find_failed_test_names(tests_out):
    """Find failed names of failed test cases in the output of the test step

    Return sorted list of names in FailedTestNames tuple
    """
    # patterns like
    # === FAIL: test_add_scalar_relu (quantization.core.test_quantized_op.TestQuantizedOps) ===
    # --- ERROR: test_all_to_all_group_cuda (__main__.TestDistBackendWithSpawn) ---
    regex = r"^[=-]+\n(FAIL|ERROR): (test_.*?)\s\(.*\n[=-]+\n"
    failed_test_cases = re.findall(regex, tests_out, re.M)
    # And patterns like:
    # FAILED test_ops_gradients.py::TestGradientsCPU::test_fn_grad_linalg_det_singular_cpu_complex128 - [snip]
    # FAILED [22.8699s] test_sparse_csr.py::TestSparseCompressedCPU::test_invalid_input_csr_large_cpu - [snip]
    # FAILED [0.0623s] dynamo/test_dynamic_shapes.py::DynamicShapesExportTests::test_predispatch -  [snip]
    regex = r"^(FAILED) (?:\[.*?\] )?(?:\w|/)+\.py.*::(test_.*?) - "
    failed_test_cases.extend(re.findall(regex, tests_out, re.M))
    return FailedTestNames(error=sorted(m[1] for m in failed_test_cases if m[0] == 'ERROR'),
                           fail=sorted(m[1] for m in failed_test_cases if m[0] != 'ERROR'))


def parse_test_log(tests_out):
    """Parse the test output and return result as TestResult tuple"""

    def get_count_for_pattern(regex, text):
        """Match the regexp containing a single group and return the integer value of the matched group.
            Return zero if no or more than 1 match was found and warn for the latter case
        """
        match = re.findall(regex, text)
        if len(match) == 1:
            return int(match[0])
        elif len(match) > 1:
            # Shouldn't happen, but means something went wrong with the regular expressions.
            # Throw warning, as the build might be fine, no need to error on this.
            warn_msg = "Error in counting the number of test failures in the output of the PyTorch test suite.\n"
            warn_msg += "Please check the EasyBuild log to verify the number of failures (if any) was acceptable."
            print_warning(warn_msg)
        return 0

    failure_cnt = 0
    error_cnt = 0
    failed_suites = []

    # Remove empty lines to make RegExs below simpler
    tests_out = re.sub(r'^[ \t]*\n', '', tests_out, flags=re.MULTILINE)

    # Grep for patterns like:
    # Ran 219 tests in 67.325s
    #
    # FAILED (errors=10, skipped=190, expected failures=6)
    # test_fx failed!
    regex = (r"^Ran (?P<test_cnt>[0-9]+) tests.*$\n"
             r"FAILED \((?P<failure_summary>.*)\)$\n"
             r"(?:^(?:(?!failed!).)*$\n){0,5}"
             r"(?P<failed_test_suite_name>.*) failed!(?: Received signal: \w+)?\s*$")

    for m in re.finditer(regex, tests_out, re.M):
        # E.g. 'failures=3, errors=10, skipped=190, expected failures=6'
        failure_summary = m.group('failure_summary')
        total, test_suite = m.group('test_cnt', 'failed_test_suite_name')
        failed_suites.append(
            TestSuiteResult(test_suite, "{total} total tests, {failure_summary}".format(
                total=total, failure_summary=failure_summary))
        )
        failure_cnt += get_count_for_pattern(r"(?<!expected )failures=([0-9]+)", failure_summary)
        error_cnt += get_count_for_pattern(r"errors=([0-9]+)", failure_summary)

    # Grep for patterns like:
    # ===================== 2 failed, 128 passed, 2 skipped, 2 warnings in 3.43s =====================
    # test_quantization failed!
    # OR:
    # ===================== 2 failed, 128 passed, 2 skipped, 2 warnings in 63.43s (01:03:43) =========
    #
    # FINISHED PRINTING LOG FILE
    # test_quantization failed!
    # OR:
    # ===================== 2 failed, 128 passed, 2 skipped, 2 warnings in 63.43s (01:03:43) =========
    # If in CI, skip info is located in the xml test reports, please either go to s3 or the hud to download them
    #
    # FINISHED PRINTING LOG FILE of test_ops_gradients (/tmp/vsc40023/easybuil...)
    #
    # test_quantization failed!

    regex = (
        r"^=+ (?P<failure_summary>.*) in [0-9]+\.*[0-9]*[a-zA-Z]* (\([0-9]+:[0-9]+:[0-9]+\) )?=+$\n"
        r"(?:.*skip info is located in the xml test reports.*\n)?"
        r"(?:.*FINISHED PRINTING LOG FILE.*\n)?"
        r"(?P<failed_test_suite_name>.*) failed!$"
    )

    for m in re.finditer(regex, tests_out, re.M):
        # E.g. '2 failed, 128 passed, 2 skipped, 2 warnings'
        failure_summary = m.group('failure_summary')
        test_suite = m.group('failed_test_suite_name')
        failed_suites.append(TestSuiteResult(test_suite, failure_summary))
        failure_cnt += get_count_for_pattern(r"([0-9]+) failed", failure_summary)
        error_cnt += get_count_for_pattern(r"([0-9]+) error", failure_summary)

    # Grep for patterns like:
    # AssertionError: 2 unit test(s) failed:
    #         DistributedDataParallelTest.test_find_unused_parameters_kwarg_debug_detail
    #         DistributedDataParallelTest.test_find_unused_parameters_kwarg_grad_is_view_debug_detail
    #
    # FINISHED PRINTING LOG FILE of distributed/test_c10d_nccl (<snip>)
    #
    # distributed/test_c10d_nccl failed!

    regex = (
        r"^AssertionError: (?P<failure_summary>[0-9]+ unit test\(s\) failed):\n"
        r"(\s+.*\n)+"
        r"(((?!failed!).)*\n){0,5}"
        r"(?P<failed_test_suite_name>.*) failed!$"
    )

    for m in re.finditer(regex, tests_out, re.M):
        # E.g. '2 unit test(s) failed'
        failure_summary = m.group('failure_summary')
        test_suite = m.group('failed_test_suite_name')
        failed_suites.append(TestSuiteResult(test_suite, failure_summary))
        failure_cnt += get_count_for_pattern(r"([0-9]+) unit test\(s\) failed", failure_summary)

    # Collect total number of tests

    # Pattern for tests ran with unittest like:
    # Ran 3 tests in 0.387s
    regex = r"^Ran (?P<test_cnt>[0-9]+) tests in"
    test_cnt = sum(int(hit) for hit in re.findall(regex, tests_out, re.M))
    # Pattern for tests ran with pytest like:
    # ============ 286 passed, 18 skipped, 2 xfailed in 38.71s ============
    regex = r"=+ (?P<summary>.*) in \d+.* =+\n"
    count_patterns = [re.compile(r"([0-9]+) " + reason) for reason in [
        "failed",
        "passed",
        "skipped",
        "deselected",
        "xfailed",
        "xpassed",
    ]]
    for m in re.finditer(regex, tests_out, re.M):
        test_cnt += sum(get_count_for_pattern(p, m.group("summary")) for p in count_patterns)

    return TestResult(test_cnt=test_cnt, error_cnt=error_cnt, failure_cnt=failure_cnt, failed_suites=failed_suites)


class EB_PyTorch(PythonPackage):
    """Support for building/installing PyTorch."""

    @staticmethod
    def extra_options():
        extra_vars = PythonPackage.extra_options()
        extra_vars.update({
            'custom_opts': [[], "List of options for the build/install command. Can be used to change the defaults " +
                                "set by the PyTorch EasyBlock, for example ['USE_MKLDNN=0'].", CUSTOM],
            'excluded_tests': [{}, "Mapping of architecture strings to list of tests to be excluded", CUSTOM],
            'max_failed_tests': [0, "Maximum number of failing tests", CUSTOM],
        })
        extra_vars['download_dep_fail'][0] = True
        extra_vars['sanity_pip_check'][0] = True
        # Make pip show output of build process as that may often contain errors or important warnings
        extra_vars['pip_verbose'][0] = True
        # Test as-if pytorch was installed
        extra_vars['testinstall'][0] = True

        return extra_vars

    def __init__(self, *args, **kwargs):
        """Constructor for PyTorch easyblock."""
        super(EB_PyTorch, self).__init__(*args, **kwargs)
        self.options['modulename'] = 'torch'

        self.tmpdir = tempfile.mkdtemp(suffix='-pytorch-build')

    def fetch_step(self, skip_checksums=False):
        """Fetch sources for installing PyTorch, including those for tests."""
        super(EB_PyTorch, self).fetch_step(skip_checksums)
        # Resolve tests early to avoid failures later. Use obtain_file if path is not absolute
        tests = [test if os.path.isabs(test) else self.obtain_file(test) for test in self.cfg['tests']]
        self.cfg['tests'] = tests

    @staticmethod
    def get_dependency_options_for_version(pytorch_version):
        """
        PyTorch can enable some functionality based on available software or use system software instead of a submodule
        This returns EasyBuild names of that and the flag that should be used when the dependency is found

        The result is a list of tuples (enable_flag, eb_name)
        """
        pytorch_version = LooseVersion(pytorch_version)

        def is_version_ok(version_range):
            """Return True if the PyTorch version to be installed matches the version_range"""
            min_version, max_version = version_range.split(':')
            result = True
            if min_version and pytorch_version < min_version:
                result = False
            if max_version and pytorch_version >= max_version:
                result = False
            return result

        available_libs = (
            # Format: (PyTorch flag to enable, EB name, '<min version>:<exclusive max version>')
            # Use `None` for the EB name if no known EC exists
            ('USE_FFMPEG=1', 'FFmpeg', '1.0.0:'),
            ('USE_GFLAGS=1', 'gflags', '1.0.0:'),
            ('USE_GLOG=1', 'glog', '1.0.0:'),

            # For system libs check CMakeLists.txt, below `if(USE_SYSTEM_LIBS)`, order kept here
            # NCCL handled specially as other env variables are requires for it
            ('USE_SYSTEM_CPUINFO=1', None, '1.6.0:'),
            ('USE_SYSTEM_SLEEF=1', None, '1.6.0:'),
            ('USE_SYSTEM_GLOO=1', None, '1.6.0:'),
            ('BUILD_CUSTOM_PROTOBUF=0', 'protobuf', '1.2.0:'),
            ('USE_SYSTEM_EIGEN_INSTALL=1', 'Eigen', '1.0.0:'),
            ('USE_SYSTEM_FP16=1', None, '1.6.0:'),
            ('USE_SYSTEM_PTHREADPOOL=1', None, '1.6.0:'),
            ('USE_SYSTEM_PSIMD=1', None, '1.6.0:'),
            ('USE_SYSTEM_FXDIV=1', None, '1.6.0:'),
            ('USE_SYSTEM_BENCHMARK=1', None, '1.6.0:'),  # Google Benchmark
            ('USE_SYSTEM_ONNX=1', None, '1.6.0:'),
            ('USE_SYSTEM_PYBIND11=1', 'pybind11', '1.10.0:'),
            ('USE_SYSTEM_XNNPACK=1', None, '1.6.0:'),
        )
        return [(enable_opt, dep_name) for enable_opt, dep_name, version_range in available_libs
                if is_version_ok(version_range)]

    def prepare_step(self, *args, **kwargs):
        """Make sure that versioned CMake alias exists"""
        super(EB_PyTorch, self).prepare_step(*args, **kwargs)
        # PyTorch preferes cmake3 over cmake which usually does not exist
        cmake_root = get_software_root('CMake')
        cmake_version = get_software_version('CMake')
        if cmake_root and not os.path.isfile(os.path.join(cmake_root, 'bin', 'cmake3')):
            if cmake_version and cmake_version.split('.')[0] != '3':
                raise EasyBuildError('PyTorch requires CMake 3 but CMake %s was found', cmake_version)
            cmake_bin_dir = tempfile.mkdtemp(suffix='cmake-bin')
            self.log.warning('Creating symlink `cmake3` in %s to avoid PyTorch picking up a system CMake. ' +
                             'Reinstall the CMake module to avoid this!', cmake_bin_dir)
            symlink(os.path.join(cmake_root, 'bin', 'cmake'), os.path.join(cmake_bin_dir, 'cmake3'))
            path = "%s:%s" % (cmake_bin_dir, os.getenv('PATH'))
            env.setvar('PATH', path)

    def configure_step(self):
        """Custom configure procedure for PyTorch."""
        super(EB_PyTorch, self).configure_step()

        pytorch_version = LooseVersion(self.version)

        # Gather default options. Will be checked against (and can be overwritten by) custom_opts
        options = ['PYTORCH_BUILD_VERSION=' + self.version, 'PYTORCH_BUILD_NUMBER=1']

        def add_enable_option(name, enabled):
            """Add `name=0` or `name=1` depending on enabled"""
            options.append('%s=%s' % (name, '1' if enabled else '0'))

        # enable verbose mode when --debug is used (to show compiler commands)
        add_enable_option('VERBOSE', build_option('debug'))

        # Restrict parallelism
        options.append('MAX_JOBS=%s' % self.cfg['parallel'])

        # BLAS Interface
        if get_software_root('imkl'):
            options.append('BLAS=MKL')
            options.append('INTEL_MKL_DIR=$MKLROOT')
        elif pytorch_version >= '1.11.0' and get_software_root('FlexiBLAS'):
            options.append('BLAS=FlexiBLAS')
            options.append('WITH_BLAS=flexi')
        elif pytorch_version >= '1.9.0' and get_software_root('BLIS'):
            options.append('BLAS=BLIS')
            options.append('BLIS_HOME=' + get_software_root('BLIS'))
            options.append('USE_MKLDNN_CBLAS=ON')
        elif get_software_root('OpenBLAS'):
            # This is what PyTorch defaults to if no MKL is found.
            # Make this explicit here to avoid it finding MKL from the system
            options.append('BLAS=Eigen')
            # Still need to set a BLAS lib to use.
            # Valid choices: mkl/open/goto/acml/atlas/accelerate/veclib/generic (+blis for 1.9+)
            options.append('WITH_BLAS=open')
            # Make sure this option is actually passed to CMake
            apply_regex_substitutions(os.path.join('tools', 'setup_helpers', 'cmake.py'), [
                ("'BLAS',", "'BLAS', 'WITH_BLAS',")
            ])
        else:
            raise EasyBuildError("Did not find a supported BLAS in dependencies. Don't know which BLAS lib to use")

        available_dependency_options = EB_PyTorch.get_dependency_options_for_version(self.version)
        dependency_names = set(dep['name'] for dep in self.cfg.dependencies())
        not_used_dep_names = []
        for enable_opt, dep_name in available_dependency_options:
            if dep_name is None:
                continue
            if dep_name in dependency_names:
                options.append(enable_opt)
            else:
                not_used_dep_names.append(dep_name)
        self.log.info('Did not enable options for the following dependencies as they are not used in the EC: %s',
                      not_used_dep_names)

        # Use Infiniband by default
        # you can disable this by including 'USE_IBVERBS=0' in 'custom_opts' in the easyconfig file
        options.append('USE_IBVERBS=1')

        if get_software_root('CUDA'):
            options.append('USE_CUDA=1')
            cudnn_root = get_software_root('cuDNN')
            if cudnn_root:
                options.append('CUDNN_LIB_DIR=' + os.path.join(cudnn_root, 'lib64'))
                options.append('CUDNN_INCLUDE_DIR=' + os.path.join(cudnn_root, 'include'))

            nccl_root = get_software_root('NCCL')
            if nccl_root:
                options.append('USE_SYSTEM_NCCL=1')
                options.append('NCCL_INCLUDE_DIR=' + os.path.join(nccl_root, 'include'))

            # list of CUDA compute capabilities to use can be specifed in two ways (where (2) overrules (1)):
            # (1) in the easyconfig file, via the custom cuda_compute_capabilities;
            # (2) in the EasyBuild configuration, via --cuda-compute-capabilities configuration option;
            cuda_cc = build_option('cuda_compute_capabilities') or self.cfg['cuda_compute_capabilities']
            if not cuda_cc:
                raise EasyBuildError('List of CUDA compute capabilities must be specified, either via '
                                     'cuda_compute_capabilities easyconfig parameter or via '
                                     '--cuda-compute-capabilities')

            self.log.info('Compiling with specified list of CUDA compute capabilities: %s', ', '.join(cuda_cc))
            # This variable is also used at runtime (e.g. for tests) and if it is not set PyTorch will automatically
            # determine the compute capability of a GPU in the system and use that which may fail tests if
            # it is to new for the used nvcc
            env.setvar('TORCH_CUDA_ARCH_LIST', ';'.join(cuda_cc))
        else:
            # Disable CUDA
            options.append('USE_CUDA=0')

        if pytorch_version >= '2.0':
            add_enable_option('USE_ROCM', get_software_root('ROCm'))
        elif pytorch_version >= 'v1.10.0':
            add_enable_option('USE_MAGMA', get_software_root('magma'))

        if get_cpu_architecture() == POWER:
            # *NNPACK is not supported on Power, disable to avoid warnings
            options.extend(['USE_NNPACK=0', 'USE_QNNPACK=0', 'USE_PYTORCH_QNNPACK=0', 'USE_XNNPACK=0'])
            # Breakpad (Added in 1.10, removed in 1.12.0) doesn't support PPC
            if pytorch_version >= '1.10.0' and pytorch_version < '1.12.0':
                options.append('USE_BREAKPAD=0')
            # FBGEMM requires AVX512, so not available on PPC
            if pytorch_version >= 'v1.10.0':
                options.append('USE_FBGEMM=0')

        # Metal only supported on IOS which likely doesn't work with EB, so disabled
        options.append('USE_METAL=0')

        unique_options = self.cfg['custom_opts']
        for option in options:
            name = option.split('=')[0] + '='  # Include the equals sign to avoid partial matches
            if not any(opt.startswith(name) for opt in unique_options):
                unique_options.append(option)

        self.cfg.update('prebuildopts', ' '.join(unique_options) + ' ')
        self.cfg.update('preinstallopts', ' '.join(unique_options) + ' ')

    def _set_cache_dir(self):
        """Set $XDG_CACHE_HOME to avoid PyTorch defaulting to $HOME"""
        cache_dir = os.path.join(self.tmpdir, '.cache')
        # The path must exist!
        mkdir(cache_dir, parents=True)
        env.setvar('XDG_CACHE_HOME', cache_dir)

    def test_step(self):
        """Run unit tests"""
        self._set_cache_dir()
        # Pretend to be on FB CI which disables some tests, especially those which download stuff
        env.setvar('SANDCASTLE', '1')
        # Skip this test(s) which is very flaky
        env.setvar('SKIP_TEST_BOTTLENECK', '1')
        # Parse excluded_tests and flatten into space separated string
        excluded_tests = []
        for arch, tests in self.cfg['excluded_tests'].items():
            if not arch or arch == get_cpu_architecture():
                excluded_tests.extend(tests)
        # -x should not be used if there are no excluded tests
        if excluded_tests:
            excluded_tests = ['-x'] + excluded_tests
        self.cfg.template_values.update({
            'python': self.python_cmd,
            'excluded_tests': ' '.join(excluded_tests)
        })

        test_result = super(EB_PyTorch, self).test_step(return_output_ec=True)
        if test_result is None:
            if self.cfg['runtest'] is False:
                msg = "Do not set 'runtest' to False, use --skip-test-step instead."
            else:
                msg = "Tests did not run. Make sure 'runtest' is set to a command."
            raise EasyBuildError(msg)

        tests_out, tests_ec = test_result

        # Show failed subtests to aid in debugging failures
        failed_test_names = find_failed_test_names(tests_out)
        if failed_test_names.error or failed_test_names.fail:
            msg = []
            if failed_test_names.error:
                msg.append("Found %d individual tests that exited with an error: %s"
                           % (len(failed_test_names.error), ', '.join(failed_test_names.error)))
            if failed_test_names.fail:
                msg.append("Found %d individual tests with failed assertions: %s"
                           % (len(failed_test_names.fail), ', '.join(failed_test_names.fail)))
            self.log.warning("\n".join(msg))

        # Create clear summary report
        test_result = parse_test_log(tests_out)
        failure_report = ['%s (%s)' % (suite.name, suite.summary) for suite in test_result.failed_suites]
        failed_test_suites = set(suite.name for suite in test_result.failed_suites)
        # Gather all failed tests suites in case we missed any (e.g. when it exited due to syntax errors)
        # Also unique to be able to compare the lists below
        all_failed_test_suites = set(
            re.findall(r"^(?P<test_name>.*) failed!(?: Received signal: \w+)?\s*$", tests_out, re.M)
        )
        # If we missed any test suites prepend a list of all failed test suites
        if failed_test_suites != all_failed_test_suites:
            failure_report = ['Failed tests (suites/files):'] + failure_report
            # Test suites where we didn't match a specific regexp and hence likely didn't count the failures
            failure_report.extend('+ %s' % t for t in sorted(all_failed_test_suites - failed_test_suites))
            # Test suites not included in the catch-all regexp but counted. Should be empty.
            failure_report.extend('? %s' % t for t in sorted(failed_test_suites - all_failed_test_suites))

        failure_report = '\n'.join(failure_report)

        # Calculate total number of unsuccesful and total tests
        failed_test_cnt = test_result.failure_cnt + test_result.error_cnt

        if failed_test_cnt > 0:
            max_failed_tests = self.cfg['max_failed_tests']

            failure_or_failures = 'failure' if test_result.failure_cnt == 1 else 'failures'
            error_or_errors = 'error' if test_result.error_cnt == 1 else 'errors'
            msg = "%d test %s, %d test %s (out of %d):\n" % (
                test_result.failure_cnt, failure_or_failures,
                test_result.error_cnt, error_or_errors,
                test_result.test_cnt
            )
            msg += failure_report

            # If no tests are supposed to fail or some failed for which we were not able to count errors fail now
            if max_failed_tests == 0 or failed_test_suites != all_failed_test_suites:
                raise EasyBuildError(msg)
            else:
                msg += '\n\n' + ' '.join([
                    "The PyTorch test suite is known to include some flaky tests,",
                    "which may fail depending on the specifics of the system or the context in which they are run.",
                    "For this PyTorch installation, EasyBuild allows up to %d tests to fail." % max_failed_tests,
                    "We recommend to double check that the failing tests listed above ",
                    "are known to be flaky, or do not affect your intended usage of PyTorch.",
                    "In case of doubt, reach out to the EasyBuild community (via GitHub, Slack, or mailing list).",
                ])
                # Print to console, the user should really be aware that we are accepting failing tests here...
                print_warning(msg)

                # Also log this warning in the file log
                self.log.warning(msg)

                if failed_test_cnt > max_failed_tests:
                    raise EasyBuildError("Too many failed tests (%d), maximum allowed is %d",
                                         failed_test_cnt, max_failed_tests)
        elif failure_report:
            raise EasyBuildError("Test ended with failures! Exit code: %s\n%s", tests_ec, failure_report)
        elif tests_ec:
            raise EasyBuildError("Test command had non-zero exit code (%s), but no failed tests found?!", tests_ec)

    def test_cases_step(self):
        self._set_cache_dir()
        super(EB_PyTorch, self).test_cases_step()

    def sanity_check_step(self, *args, **kwargs):
        """Custom sanity check for PyTorch"""

        if self.cfg.get('download_dep_fail', True):
            # CMake might mistakenly download dependencies during configure
            self.log.info('Checking for downloaded submodules')
            pattern = r'^-- Downloading (\w+) to /'
            downloaded_deps = re.findall(pattern, self.install_cmd_output, re.M)

            if downloaded_deps:
                self.log.info('Found downloaded submodules: %s', ', '.join(downloaded_deps))
                fail_msg = 'found one or more downloaded dependencies: %s' % ', '.join(downloaded_deps)
                self.sanity_check_fail_msgs.append(fail_msg)

        super(EB_PyTorch, self).sanity_check_step(*args, **kwargs)

    def make_module_req_guess(self):
        """Set extra environment variables for PyTorch."""

        guesses = super(EB_PyTorch, self).make_module_req_guess()
        guesses['CMAKE_PREFIX_PATH'] = [os.path.join(self.pylibdir, 'torch')]
        # Required to dynamically load libcaffe2_nvrtc.so
        guesses['LD_LIBRARY_PATH'] = [os.path.join(self.pylibdir, 'torch', 'lib')]
        return guesses


if __name__ == '__main__':
    arg = sys.argv[1]
    if not os.path.isfile(arg):
        raise RuntimeError('Expected a test result file to parse, got: ' + arg)
    with open(arg, 'r') as f:
        content = f.read()
    m = re.search(r'cmd .*python[^ ]* run_test\.py .* exited with exit code.*output', content)
    if m:
        content = content[m.end():]
        # Heuristic for next possible text added by EasyBuild
        m = re.search(r'^== \d+-\d+-\d+ .* (pytorch\.py|EasyBuild)', content)
        if m:
            content = content[:m.start()]

    print("Failed test names: ", find_failed_test_names(content))
    print("Test result: ", parse_test_log(content))
