#! /usr/bin/env python
##
# Copyright 2020-2025 Ghent University
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
import xml.etree.ElementTree as ET
from collections import Counter
from enum import Enum
from itertools import chain, groupby
from operator import attrgetter
from pathlib import Path
from typing import Dict, Iterable, List

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools import LooseVersion
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import ERROR, build_option
from easybuild.tools.filetools import apply_regex_substitutions, mkdir, symlink
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import POWER, get_cpu_architecture

if sys.version_info >= (3, 9):
    from dataclasses import dataclass

    @dataclass
    class FailedTestNames:
        """Hold list of tests names that failed with error or failure"""
        error: list[str]
        fail: list[str]

    @dataclass
    class TestSuiteResult:
        """Hold the name of a test suite and a summary of the failures"""
        name: str
        summary: str

    @dataclass
    class TestResult:
        """Status report and results of a test run"""
        test_cnt: int
        error_cnt: int
        failure_cnt: int
        failed_suites: list[TestSuiteResult]
        terminated_suites: dict[str, str]  # Name and signal of terminated suites
        all_failed_suites: set[str]  # Names of all failed suites
else:
    from collections import namedtuple
    FailedTestNames = namedtuple('FailedTestNames', ('error', 'fail'))
    TestSuiteResult = namedtuple('TestSuiteResult', ('name', 'summary'))
    TerminatedTestSuite = namedtuple('TerminatedTestSuite', ('name', 'signal'))
    TestResult = namedtuple('TestResult', ('test_cnt',
                                           'error_cnt',
                                           'failure_cnt',
                                           'failed_suites',
                                           'terminated_suites',
                                           'all_failed_suites'
                                           ))


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
    return FailedTestNames(error=sorted(set(m[1] for m in failed_test_cases if m[0] == 'ERROR')),
                           fail=sorted(set(m[1] for m in failed_test_cases if m[0] != 'ERROR')))


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

    # Examples: "test_jit_profiling failed! Received signal: SIGSEGV"
    #           "test_weak failed!"
    #           "test_decomp 1/1 failed!"
    #           "test_pytree 1/1 failed! [Errno 2] No such file or directory: '/dev/shm/build/...'"
    suite_failed_pattern = (r"^(?P<failed_test_suite_name>.*?) (?:\d+/\d+ )?failed!"
                            r"(?: Received signal: (\w+)| \[Errno \d+\] .*)?\s*$")

    # Grep for patterns like:
    # Ran 219 tests in 67.325s
    #
    # FAILED (errors=10, skipped=190, expected failures=6)
    # test_fx failed!
    regex = (r"^Ran (?P<test_cnt>[0-9]+) tests.*$\n"
             r"FAILED \((?P<failure_summary>.*)\)$\n"
             r"(?:^(?:(?!failed!).)*$\n){0,5}"
             + suite_failed_pattern)

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
        + suite_failed_pattern
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
        + suite_failed_pattern
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

    # Gather all failed tests suites in case we missed any,
    # e.g. when it exited due to syntax errors or with a signal such as SIGSEGV
    failed_suites_and_signal = set(re.findall(suite_failed_pattern, tests_out, re.M))

    return TestResult(test_cnt=test_cnt, error_cnt=error_cnt, failure_cnt=failure_cnt,
                      failed_suites=failed_suites,
                      # Assumes that the suite name is unique
                      terminated_suites={name: signal for name, signal in failed_suites_and_signal if signal},
                      all_failed_suites={i[0] for i in failed_suites_and_signal})


class EB_PyTorch(PythonPackage):
    """Support for building/installing PyTorch."""

    GENERATE_TEST_REPORT_VAR_NAME = 'EASYBUILD_WRITE_PYTORCH_TEST_REPORTS'

    @staticmethod
    def extra_options():
        extra_vars = PythonPackage.extra_options()
        extra_vars.update({
            'build_type': [None, "Build type for CMake, e.g. Release."
                                 "Defaults to 'Release' or 'Debug' depending on toolchainopts[debug]", CUSTOM],
            'custom_opts': [[], "List of options for the build/install command. Can be used to change the defaults " +
                                "set by the PyTorch EasyBlock, for example ['USE_MKLDNN=0'].", CUSTOM],
            'excluded_tests': [{}, "Mapping of architecture strings to list of tests to be excluded", CUSTOM],
            'max_failed_tests': [0, "Maximum number of failing tests", CUSTOM],
        })

        # disable use of pip to install PyTorch by default, overwriting the default set in PythonPackage;
        # see also https://github.com/easybuilders/easybuild-easyblocks/pull/3022
        extra_vars['use_pip'][0] = None

        # Make pip show output of build process as that may often contain errors or important warnings
        extra_vars['pip_verbose'][0] = True
        # Test as-if pytorch was installed
        extra_vars['testinstall'][0] = True

        return extra_vars

    def __init__(self, *args, **kwargs):
        """Constructor for PyTorch easyblock."""
        super(EB_PyTorch, self).__init__(*args, **kwargs)
        self.options['modulename'] = 'torch'
        self.has_xml_test_reports = False

        self.tmpdir = tempfile.mkdtemp(suffix='-pytorch-build')

        # opt-in to using pip to install PyTorch for sufficiently recent version (>= 2.0),
        # unless it's otherwise specified
        pytorch_version = LooseVersion(self.version)
        if self.cfg['use_pip'] is None and pytorch_version >= '2.0':
            self.log.info("Auto-enabling use of pip to install PyTorch >= 2.0, since 'use_pip' is not set")
            self.cfg['use_pip'] = True
            self.determine_install_command()

        # Set extra environment variables for PyTorch
        # use glob pattern as self.pylibdir is unknown at this stage
        # it will be expanded before injection into the module file
        py_site_glob = os.path.join('lib', 'python*', 'site-packages')
        self.module_load_environment.CMAKE_PREFIX_PATH = [os.path.join(py_site_glob, 'torch')]
        # required to dynamically load libcaffe2_nvrtc.so
        self.module_load_environment.LD_LIBRARY_PATH = [os.path.join(py_site_glob, 'torch', 'lib')]
        # important when RPATH linking is enabled
        self.module_load_environment.LIBRARY_PATH = [os.path.join(py_site_glob, 'torch', 'lib')]

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

        self.has_xml_test_reports = False
        if pytorch_version >= '1.10.0':
            res = run_shell_cmd(self.python_cmd + " -c 'import xmlrunner'", fail_on_error=False)
            if res.exit_code != 0:
                msg = ("Python package xmlrunner (unittest-xml-reporting) not found in dependencies of the "
                       "PyTorch EasyConfig, can't enable advanced test result checks. Output: " + res.output)
                # We introduced this in the 2.3 EasyConfig
                if pytorch_version >= '2.3':
                    print_warning(msg)
                else:
                    self.log.warning(msg)
            else:
                # Replace the condition to enable the XML test reports to use our variable instead of $IS_CI/$IS_IN_CI
                # The variable is used because the file gets installed and we shouldn't change the default behavior.
                apply_regex_substitutions('torch/testing/_internal/common_utils.py',
                                          [(r'(default=_get_test_report_path\(\) if) IS(_IN)?_CI else None',
                                            fr'\1 os.getenv("{self.GENERATE_TEST_REPORT_VAR_NAME}") else None')],
                                          backup=False, on_missing_match=ERROR)
                if pytorch_version >= '2.1.0':
                    run_test_subs = [(r'if IS_CI:\n\s+# Add the option to generate XML test report.*',
                                      'if TEST_SAVE_XML:\n')]
                else:
                    run_test_subs = [
                         (r'from torch.testing._internal.common_utils import\s+\(\n\s+',
                          r'\g<0>get_report_path, '),
                         (r'# If using pytest.*\n\s+if options.pytest:\n\s+unittest_args = \[',
                          r'\g<0>"--junit-xml-reruns", get_report_path(pytest=True)] + ['),
                    ]
                apply_regex_substitutions('test/run_test.py', run_test_subs, backup=False, on_missing_match=ERROR,
                                          single_line=False)
                self.has_xml_test_reports = True

        # Gather default options. Will be checked against (and can be overwritten by) custom_opts
        options = ['PYTORCH_BUILD_VERSION=' + self.version, 'PYTORCH_BUILD_NUMBER=1']

        def add_enable_option(name, enabled):
            """Add `name=0` or `name=1` depending on enabled"""
            options.append('%s=%s' % (name, '1' if enabled else '0'))

        # enable verbose mode when --debug is used (to show compiler commands)
        add_enable_option('VERBOSE', build_option('debug'))

        # Restrict parallelism
        options.append(f'MAX_JOBS={self.cfg.parallel}')

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

        build_type = self.cfg.get('build_type')
        if build_type is None:
            build_type = 'Debug' if self.toolchain.options.get('debug', None) else 'Release'
        else:
            for name in ('prebuildopts', 'preinstallopts', 'custom_opts'):
                if '-DCMAKE_BUILD_TYPE=' in self.cfg[name]:
                    self.log.warning('CMAKE_BUILD_TYPE is set in %s. Ignoring build_type', name)
                    build_type = None
        if build_type:
            if pytorch_version >= '1.2.0':
                options.append('CMAKE_BUILD_TYPE=' + build_type)
            else:
                # Older versions use 2 env variables defaulting to "Release" if none are set
                build_type = build_type.lower()
                add_enable_option('DEBUG', build_type == 'debug')
                add_enable_option('REL_WITH_DEB_INFO', build_type == 'relwithdebinfo')

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

    def _compare_test_results(self, old_result, xml_result, old_failed_test_names, xml_failed_test_names):
        """Compare test results parsed from stdout and XML files"""
        diffs = []

        old_suite_names = {suite.name for suite in old_result.failed_suites}
        new_suite_names = {suite.name for suite in xml_result.failed_suites}
        new_suites = new_suite_names - old_suite_names
        missing_suites = old_suite_names - new_suite_names

        diffs = []
        if new_suites:
            diffs.append(f'Found {len(new_suites)} new suites in XML files: {", ".join(sorted(new_suites))}')
        if missing_suites:
            diffs.append(f'Did not find {len(missing_suites)} suites in XML files: ' +
                         ", ".join(sorted(missing_suites)))
        if xml_result.test_cnt != old_result.test_cnt:
            diffs.append(f'Different number of tests in XML files: {xml_result.test_cnt} != {old_result.test_cnt}')
        if xml_result.error_cnt != old_result.error_cnt:
            diffs.append(f'Different number of test errors in XML files: '
                         f'{xml_result.error_cnt} != {old_result.error_cnt}')
        if xml_result.failure_cnt != old_result.failure_cnt:
            diffs.append(f'Different number of test failures in XML files: '
                         f'{xml_result.failure_cnt} != {old_result.failure_cnt}')

        def get_test_name_diff(lst_should, lst_is):
            # Handle the case where one includes the class name and the other doesn't
            return [name for name in lst_is
                    if not any(name == name2 or
                               name.endswith(f'.{name2}') or
                               name2.endswith(f'.{name}') for name2 in lst_should)]
        new_tests = get_test_name_diff(old_failed_test_names.error, xml_failed_test_names.error)
        missing_tests = get_test_name_diff(xml_failed_test_names.error, old_failed_test_names.error)
        if new_tests:
            diffs.append(f'Found {len(new_tests)} new tests with errors in XML files: {", ".join(sorted(new_tests))}')
        if missing_tests:
            diffs.append(f'Did not find {len(missing_tests)} tests with errors in XML files: ' +
                         ", ".join(sorted(missing_tests)))
        new_tests = get_test_name_diff(old_failed_test_names.fail, xml_failed_test_names.fail)
        missing_tests = get_test_name_diff(xml_failed_test_names.fail, old_failed_test_names.fail)
        if new_tests:
            diffs.append(f'Found {len(new_tests)} new failed tests in XML files: {", ".join(sorted(new_tests))}')
        if missing_tests:
            diffs.append(f'Did not find {len(missing_tests)} failed tests in XML files: ' +
                         ", ".join(sorted(missing_tests)))
        if diffs:
            self.log.warning("Found differences when parsing stdout and XML files:\n\t" + "\n\t".join(diffs))

    def test_step(self):
        """Run unit tests"""
        self._set_cache_dir()
        # Pretend to be on FB CI which disables some tests, especially those which download stuff
        env.setvar('SANDCASTLE', '1')
        # Skip this test(s) which is very flaky
        env.setvar('SKIP_TEST_BOTTLENECK', '1')
        if self.has_xml_test_reports:
            env.setvar(self.GENERATE_TEST_REPORT_VAR_NAME, '1')
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

        parsed_test_result = super(EB_PyTorch, self).test_step(return_output_ec=True)
        if parsed_test_result is None:
            if self.cfg['runtest'] is False:
                msg = "Do not set 'runtest' to False, use --skip-test-step instead."
            else:
                msg = "Tests did not run. Make sure 'runtest' is set to a command."
            raise EasyBuildError(msg)

        tests_out, tests_ec = parsed_test_result

        failed_test_names = find_failed_test_names(tests_out)
        parsed_test_result = parse_test_log(tests_out)

        if self.has_xml_test_reports:
            test_reports_path = Path(self.start_dir) / 'test' / 'test-reports'
            try:
                xml_results = get_test_results(test_reports_path)
            except ValueError as e:
                raise EasyBuildError(f"Failed to parse test results at {test_reports_path}: {e}")
            if not xml_results:
                files = [file for file in test_reports_path.rglob('*.*') if file.is_file()]
                if files:
                    msg = f'Did not find any test result at {test_reports_path}. Files: {", ".join(files)}'
                else:
                    msg = f'Failed to find any test report files at {test_reports_path}'
                raise EasyBuildError(msg)
            missing_suites = [suite.name for suite in parsed_test_result.failed_suites
                              if suite.name not in xml_results]
            if missing_suites:
                raise EasyBuildError('Parsing the test result files missed the following failed suites: %s',
                                     ', '.join(sorted(missing_suites)))
            # Replace results as the files should be more reliable than the parsed ones
            new_result = TestResult(test_cnt=sum(suite.num_tests for suite in xml_results.values()),
                                    error_cnt=sum(suite.errors for suite in xml_results.values()),
                                    failure_cnt=sum(suite.failures for suite in xml_results.values()),
                                    failed_suites=[suite for suite in xml_results.values()
                                                   if suite.failures + suite.errors > 0],
                                    terminated_suites=parsed_test_result.terminated_suites,
                                    all_failed_suites=parsed_test_result.all_failed_suites)
            new_failed_names = FailedTestNames(
                error=list(chain.from_iterable(suite.get_errored_tests() for suite in xml_results.values())),
                fail=list(chain.from_iterable(suite.get_failed_tests() for suite in xml_results.values()))
            )
            if LooseVersion(self.version) < '2.3':
                # Show differences to results parsed from logfile. In 2.3+ the parsed values are no longer reliable
                self._compare_test_results(parsed_test_result, new_result, failed_test_names, new_failed_names)
            parsed_test_result = new_result
            failed_test_names = new_failed_names

        # Show failed subtests, if any, to aid in debugging failures
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
        # Use a list of messages we can later join together
        failure_msgs = ['\t%s (%s)' % (suite.name, suite.summary) for suite in parsed_test_result.failed_suites]
        # These were accounted for
        failed_test_suites = set(suite.name for suite in parsed_test_result.failed_suites)
        # Those are all that failed according to the summary output
        all_failed_test_suites = parsed_test_result.all_failed_suites
        # We should have determined all failed test suites and only those.
        # Otherwise show the mismatch and terminate later
        if failed_test_suites != all_failed_test_suites:
            failure_msgs.insert(0, 'Failed tests (suites/files):')
            # Test suites where we didn't match a specific regexp and hence likely didn't count the failures
            uncounted_test_suites = all_failed_test_suites - failed_test_suites
            if uncounted_test_suites:
                failure_msgs.append('Could not count failed tests for the following test suites/files:')
                for suite_name in sorted(uncounted_test_suites):
                    try:
                        signal = parsed_test_result.terminated_suites[suite_name]
                        reason = f'Terminated with {signal}'
                    except KeyError:
                        # Not ended with signal, might have failed due to e.g. syntax errors
                        reason = 'Undetected or did not run properly'
                    failure_msgs.append(f'\t{suite_name} ({reason})')
            # Test suites not included in the catch-all regexp but counted. Should be empty.
            unexpected_test_suites = failed_test_suites - all_failed_test_suites
            if unexpected_test_suites:
                failure_msgs.append('Counted failures of tests from the following test suites/files that are not '
                                    'contained in the summary output of PyTorch:')
                failure_msgs.extend(sorted(unexpected_test_suites))

        # Calculate total number of unsuccesful and total tests
        failed_test_cnt = parsed_test_result.failure_cnt + parsed_test_result.error_cnt
        # Only add count message if we detected any failed tests
        if failed_test_cnt > 0:
            failure_or_failures = 'failure' if parsed_test_result.failure_cnt == 1 else 'failures'
            error_or_errors = 'error' if parsed_test_result.error_cnt == 1 else 'errors'
            failure_msgs.insert(0, "%d test %s, %d test %s (out of %d):" % (
                parsed_test_result.failure_cnt, failure_or_failures,
                parsed_test_result.error_cnt, error_or_errors,
                parsed_test_result.test_cnt
            ))

        # Assemble final report
        failure_report = '\n'.join(failure_msgs)

        if failed_test_suites != all_failed_test_suites:
            # Fail because we can't be sure how many tests failed
            # so comparing to max_failed_tests cannot reasonably be done
            if failed_test_suites | set(parsed_test_result.terminated_suites) == all_failed_test_suites:
                # All failed test suites are either counted or terminated with a signal
                msg = ('Failing because these test suites were terminated which makes it impossible '
                       'to accurately count the failed tests: ')
                msg += ", ".join("%s(%s)" % name_signal
                                 for name_signal in sorted(parsed_test_result.terminated_suites.items()))
            elif len(failed_test_suites) < len(all_failed_test_suites):
                msg = ('Failing because not all failed tests could be determined. Tests failed to start, crashed '
                       'or the test accounting in the PyTorch EasyBlock needs updating!\n'
                       'Missing: ' + ', '.join(sorted(all_failed_test_suites - failed_test_suites)))
            else:
                msg = ('Failing because there were unexpected failures detected: ' +
                       ', '.join(sorted(failed_test_suites - all_failed_test_suites)))
            raise EasyBuildError(msg + '\n' +
                                 'You can check the test failures (in the log) manually and if they are harmless, '
                                 'use --ignore-test-failures to make the test step pass.\n' + failure_report)

        if failed_test_cnt > 0:
            max_failed_tests = self.cfg['max_failed_tests']

            # If no tests are supposed to fail don't print the explanation, just fail
            if max_failed_tests == 0:
                raise EasyBuildError(failure_report)
            msg = failure_report + '\n\n' + ''.join([
                "The PyTorch test suite is known to include some flaky tests, ",
                "which may fail depending on the specifics of the system or the context in which they are run.\n",
                f"For this PyTorch installation, EasyBuild allows up to {max_failed_tests} tests to fail.\n",
                "We recommend to double check that the failing tests listed above ",
                "are known to be flaky, or do not affect your intended usage of PyTorch.\n",
                "In case of doubt, reach out to the EasyBuild community (via GitHub, Slack, or mailing list).",
            ])
            # Print to console in addition to file,
            # the user should really be aware that we are accepting failing tests here...
            print_warning(msg, log=self.log)

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


# ###################################### Code for parsing PyTorch Test XML files ######################################
class TestState(Enum):
    """Result of a test case run"""
    SUCCESS, FAILURE, ERROR, SKIPPED = "success", "failure", "error", "skipped"


if sys.version_info >= (3, 9):
    from dataclasses import dataclass

    @dataclass
    class TestCase:
        """Instance of a test method run"""
        name: str
        state: TestState
        num_reruns: int
else:
    from collections import namedtuple
    TestCase = namedtuple('TestCase', ('name', 'state', 'num_reruns'))


class TestSuite:
    """Collection of tests in the same test file"""

    def __init__(self, name: str, errors: int, failures: int, skipped: int, test_cases: Dict[str, TestCase]):
        num_per_state = Counter(test_case.state for test_case in test_cases.values())
        if skipped != num_per_state[TestState.SKIPPED]:
            raise ValueError(f'Expected {skipped} skipped tests but found {num_per_state[TestState.SKIPPED]}')
        if failures != num_per_state[TestState.FAILURE]:
            raise ValueError(f'Expected {failures} failed tests but found {num_per_state[TestState.FAILURE]}')
        if errors != num_per_state[TestState.ERROR]:
            raise ValueError(f'Expected {errors} errored tests but found {num_per_state[TestState.ERROR]}')

        self.name = name
        self.errors = errors
        self.failures = failures
        self.skipped = skipped
        self.test_cases = test_cases

    def __getitem__(self, name: str) -> TestCase:
        """Return testcase by name"""
        return self.test_cases[name]

    def _adjust_count(self, state: TestState, val: int):
        """Adjust the relevant state count"""
        if state == TestState.FAILURE:
            self.failures += val
        elif state == TestState.SKIPPED:
            self.skipped += val
        elif state == TestState.ERROR:
            self.errors += val
        elif state != TestState.SUCCESS:
            raise ValueError(f'Invalid state {state}')

    @property
    def num_tests(self) -> int:
        """Return the total number of tests"""
        return len(self.test_cases)

    @property
    def summary(self) -> str:
        """Return a textual sumary"""
        num_passed = len(self.test_cases) - self.errors - self.failures - self.skipped
        return f'{self.failures} failed, {num_passed} passed, {self.skipped} skipped, {self.errors} errors'

    def get_tests(self) -> Iterable[TestCase]:
        """Return all test instances"""
        return self.test_cases.values()

    def add_test(self, test: TestCase):
        """Add a test instance"""
        if test.name in self.test_cases:
            raise ValueError(f"Duplicate test case '{test}' in test suite {self.name}")
        self.test_cases[test.name] = test
        self._adjust_count(test.state, 1)

    def replace_test(self, test: TestCase):
        """Replace an existing test instance"""
        existing_test = self.test_cases.pop(test.name)
        self._adjust_count(existing_test.state, -1)
        self.add_test(test)

    def get_errored_tests(self) -> List[str]:
        """Return a list of test names that exited with an error"""
        return [test.name for test in self.test_cases.values() if test.state == TestState.ERROR]

    def get_failed_tests(self) -> List[str]:
        """Return a list of failed test names"""
        return [test.name for test in self.test_cases.values() if test.state == TestState.FAILURE]


def parse_test_cases(test_suite_el: ET.Element) -> List[TestCase]:
    """Extract all test cases from the testsuite XML element"""
    test_cases: List[TestCase] = []
    for testcase in test_suite_el.iterfind("testcase"):
        classname = testcase.attrib["classname"]
        test_name = f'{classname}.{testcase.attrib["name"]}'
        failed, errored, skipped = [testcase.find(tag) is not None for tag in ("failure", "error", "skipped")]
        num_reruns = len(testcase.findall("rerun"))

        if skipped:
            if num_reruns > 0 or failed or errored:
                raise ValueError(f"Invalid state for testcase '{test_name}'")
            state = TestState.SKIPPED
        else:
            state = TestState.FAILURE if failed else TestState.ERROR if errored else TestState.SUCCESS

        test_cases.append(TestCase(test_name, state=state, num_reruns=num_reruns))
    return test_cases


def determine_suite_name(xml_file: Path, test_suite_xml: List[ET.Element]) -> str:
    """Determine main test suite name from path(s) to match against run_test.py output"""
    # Gather all file attributes from the test cases if set
    test_cases = [testcase for suite in test_suite_xml for testcase in suite.iterfind("testcase")]
    file_attribute = {testcase.attrib.get("file") for testcase in test_cases}
    file_attribute.discard(None)
    suite_name = xml_file.parent.name.replace('.', os.path.sep)  # Usually the suite name is the folder name
    if xml_file.name.startswith('TEST-'):
        # Python unittest reports have 1 file per test class:
        # test-reports/python-unittest/test_package/TEST-test_repackage.TestRepackage-20250217120914.xml
        # -> test_repackage.py ran TestRepackage
        # test-reports/dist-gloo/distributed.algorithms.test_quantization/TEST-DistQuantizationTests-20250123170925.xml
        # -> distributed/algorithms/test_quantization ran DistQuantizationTests in dist-gloo variant
        # Just do a sanity check
        if len(file_attribute) > 1:
            raise ValueError(f"Found multiple reported files in unittest report of '{xml_file}': {file_attribute}")
        reported_file = os.path.basename(file_attribute.pop())

        name_parts = xml_file.name[len('TEST-'):].rsplit('-', 1)[0].rsplit('.', 2)
        # If there is only one part it is the class -> filename is in the suite name
        if len(name_parts) == 1:
            test_file_name = os.path.basename(suite_name) + '.py'
        else:
            # Note that multiple parts are possible for sub-test files:
            # TEST-jit.test_builtins.TestBuiltins (jit/test_builtins.py)
            test_file_name = name_parts[-2] + '.py'
        if test_file_name != reported_file:
            raise ValueError(f"Unexpected file attributes in test cases of '{xml_file}'. "
                             f"Expected {test_file_name}, got {file_attribute}")
    elif suite_name == 'run_test':
        # Generic report, so try to infer from the class names which look like
        # test.distributed.pipeline.sync.test_stream.TestGetDevice or
        # test.distributed.pipeline.sync.test_pipe
        # distributed.elastic.events.lib_test.RdzvEventLibTest
        def extract_path(classname: str) -> str:
            parts = classname.split('.')
            if parts[0] == 'test':
                if not parts[-1].startswith('test_') and 'Test' in parts[-1]:
                    # last part is a real class name
                    parts.pop()
                return os.path.join(*parts[1:])
            return None
        possible_paths = {extract_path(testcase.attrib["classname"]) for testcase in test_cases}
        possible_paths.discard(None)
        if not possible_paths:
            raise ValueError("Could not infer test suite name from class names for {xml_file}.")
        # We can remove possible class names by only using the common part
        suite_name = os.path.commonpath(possible_paths)
        # Strip of common prefix to all classes, but keep the last part for uniqueness
        non_classname_prefix = os.path.dirname(suite_name).replace(os.path.sep, '.') + '.'
        for testcase in test_cases:
            classname = testcase.attrib["classname"]
            if classname.startswith(non_classname_prefix):
                testcase.attrib["classname"] = classname[len(non_classname_prefix):]
    else:
        # Pytest reports, have the name in folder and file e.g.:
        # distributed.pipeline.sync.skip.test_stash_pop/distributed.pipeline.sync.skip.test_stash_pop-052ae03efad18.xml
        # -> distributed/pipeline/sync/skip/test_stash_pop
        test_file_path = xml_file.name.rsplit('-', 1)[0].replace('.', os.path.sep)
        if test_file_path != suite_name:
            raise ValueError(f"Path from folder and filename should be equal. "
                             f"Got: '{test_file_path}' != '{suite_name}'")
    # Variant might be dist-gloo, dist-mpi or similar which is the same test code ran in different configurations!
    variant = xml_file.parent.parent.name
    if variant not in ('python-unittest', 'python-pytest'):
        suite_name = os.path.join(variant, suite_name)
    return suite_name


def parse_test_result_file(xml_file: Path) -> List[TestSuite]:
    """
    Parses the given XML file into TestSuite and TestCase objects.

    :param file_path: Path to an XML file storing test results.
    :return: A list of TestSuite objects representing the parsed structure.
    """
    root = ET.parse(xml_file).getroot()

    # Normalize root to be a list of test suite elements
    if root.tag == "testsuites":
        test_suite_xml: List[ET.Element] = root.findall("testsuite")
    elif root.tag == "testsuite":
        test_suite_xml = [root]
    else:
        raise ValueError("Root element must be <testsuites> or <testsuite>.")

    # Suite name to correctly deduplicate tests and match against run_test.py output
    suite_name = determine_suite_name(xml_file, test_suite_xml)

    test_suites: List[TestSuite] = []

    for test_suite in test_suite_xml:
        errors = int(test_suite.attrib["errors"])
        failures = int(test_suite.attrib["failures"])
        skipped = int(test_suite.attrib["skipped"])
        num_tests = int(test_suite.attrib["tests"])
        if num_tests < failures + skipped + errors:
            raise ValueError(f"Invalid test count: "
                             f"{num_tests} tests, {failures} failures, {skipped} skipped, {errors} errors")

        parsed_test_cases = parse_test_cases(test_suite)
        if not parsed_test_cases:
            # No data about the test cases or even the name of the suite, so ignore it
            if num_tests > 0:
                raise ValueError("Testsuite contains no test cases, but reports tests.")
            continue

        test_cases: Dict[str, TestCase] = {}
        for test_case in parsed_test_cases:
            if test_case.name in test_cases:
                raise ValueError(f"Duplicate test case '{test_case}' in test suite {suite_name}")
            test_cases[test_case.name] = test_case

        if len(test_cases) != num_tests:
            raise ValueError(f"Number of test cases does not match the total number of tests: "
                             f"{len(test_cases)} vs. {num_tests}")
        test_suites.append(
            TestSuite(name=suite_name, test_cases=test_cases,
                      errors=errors, failures=failures, skipped=skipped,
                      )
        )
    return test_suites


def merge_test_suites(test_suites: Iterable[TestSuite]) -> TestSuite:
    """
    Combine results for all given test suites into a single instance.
    If there is only a single instance in the input, it is returned as is.
    """
    test_suites = iter(test_suites)
    result_suite: TestSuite = next(test_suites)
    for current_suite in test_suites:
        for current_test in current_suite.get_tests():
            try:
                existing_test = result_suite[current_test.name]
            except KeyError:
                result_suite.add_test(current_test)
            else:
                if (existing_test.state == TestState.SKIPPED) != (current_test.state == TestState.SKIPPED):
                    raise ValueError(f"Mismatch in whether test was skipped or not in suite {result_suite.name}: "
                                     f"{existing_test} vs. {current_test}")
                # If test was rerun and succeeded use that
                if current_test.state == TestState.SUCCESS and existing_test.state != TestState.SUCCESS:
                    result_suite.replace_test(current_test)
    return result_suite


def get_test_results(folder: Path) -> Dict[str, TestSuite]:
    """Return a dictionary of test results contained in the folder"""
    if folder.name.startswith('test-reports'):
        folders = [folder]
    else:
        # Gather all folders containing test-reports which might be named "test-reports_1"
        # Fallback to only the folder
        folders = [cur_dir for cur_dir in folder.glob('test-reports*') if cur_dir.is_dir()] or [folder]

    files = (file for folder in folders for file in folder.rglob('*.xml'))
    test_suites = chain.from_iterable(parse_test_result_file(file) for file in files)
    get_name = attrgetter('name')
    test_suites = sorted(test_suites, key=get_name)
    return {name: merge_test_suites(suites) for name, suites in groupby(test_suites, get_name)}


def main(arg: Path):
    if arg.is_file():
        content = arg.read_text()
        m = re.search(r'cmd .*python[^ ]* run_test\.py .* exited with exit code.*output', content)
        if m:
            content = content[m.end():]
            # Heuristic for next possible text added by EasyBuild
            m = re.search(r'^== \d+-\d+-\d+ .* (pytorch\.py|EasyBuild)', content)
            if m:
                content = content[:m.start()]

        print("Failed test names: ", find_failed_test_names(content))
        print("Test result: ", parse_test_log(content))
    elif not arg.is_dir():
        msg = f'Expected a test result file or folder with XMLs to parse, got: {arg}'
        if not arg.exists():
            msg += ' which does not exist'
        raise RuntimeError(msg)
    else:
        results = get_test_results(Path(arg))
        print(f"Found {len(results)} test suites:")
        for suite in results.values():
            print(f"Suite {suite.name} {suite.num_tests}:\t{suite.summary}")
        print("Total tests:", sum(suite.num_tests for suite in results.values()))
        print("Total failures:", sum(suite.failures for suite in results.values()))
        print("Total skipped:", sum(suite.skipped for suite in results.values()))
        print("Total errors:", sum(suite.errors for suite in results.values()))
        failed_suites = [suite.name for suite in results.values() if suite.failures + suite.errors > 0]
        print(f"Failed suites ({len(failed_suites)}):\n\t" + '\n\t'.join(sorted(failed_suites)))
        failed_tests = sum((suite.get_failed_tests() for suite in results.values()), [])
        print(f"Failed tests ({len(failed_tests)}):\n\t" + '\n\t'.join(sorted(failed_tests)))
        errored_tests = sum((suite.get_errored_tests() for suite in results.values()), [])
        print(f"Errored tests ({len(errored_tests)}):\n\t" + '\n\t'.join(sorted(errored_tests)))


if __name__ == '__main__':
    main(Path(sys.argv[1]))
