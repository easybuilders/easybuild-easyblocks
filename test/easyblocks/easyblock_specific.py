##
# Copyright 2019-2023 Ghent University
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
Unit tests for specific easyblocks.

@author: Kenneth Hoste (Ghent University)
"""
import copy
import os
import stat
import sys
import tempfile
import textwrap
from unittest import TestLoader, TextTestRunner
from test.easyblocks.module import cleanup

import easybuild.tools.options as eboptions
from easybuild.base.testing import TestCase
from easybuild.easyblocks.generic.cmakemake import det_cmake_version
from easybuild.easyblocks.generic.toolchain import Toolchain
from easybuild.easyblocks import pytorch
from easybuild.framework.easyblock import EasyBlock, get_easyblock_instance
from easybuild.framework.easyconfig.easyconfig import process_easyconfig
from easybuild.tools import config
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import GENERAL_CLASS, get_module_syntax
from easybuild.tools.environment import modify_env
from easybuild.tools.filetools import adjust_permissions, remove_dir, write_file
from easybuild.tools.modules import modules_tool
from easybuild.tools.options import set_tmpdir
from easybuild.tools.py2vs3 import StringIO

PYTORCH_TESTS_OUTPUT = """
...
AssertionError: Expected zero exit code but got -6 for pid: 2006681

----------------------------------------------------------------------
Ran 2 tests in 6.576s

FAILED (failures=2)
distributed/fsdp/test_fsdp_input failed!
Running distributed/fsdp/test_fsdp_multiple_forward ... [2023-01-12 05:46:45.746098]

RuntimeError: Process 0 terminated or timed out after 610.0615825653076 seconds

----------------------------------------------------------------------
Ran 1 test in 610.744s

FAILED (errors=1)
Test exited with non-zero exitcode 1. Command to reproduce: /software/Python/3.9.6-GCCcore-11.2.0/bin/python distributed/test_c10d_gloo.py -v DistributedDataParallelTest.test_ddp_comm_hook_register_just_once

RuntimeError: Process 0 terminated or timed out after 610.0726096630096 seconds

----------------------------------------------------------------------
Ran 1 test in 610.729s

FAILED (errors=1)
Test exited with non-zero exitcode 1. Command to reproduce: /software/Python/3.9.6-GCCcore-11.2.0/bin/python distributed/test_c10d_gloo.py -v DistributedDataParallelTest.test_ddp_invalid_comm_hook_init
test_ddp_invalid_comm_hook_return_type (__main__.DistributedDataParallelTest)

AssertionError: 4 unit test(s) failed:
    DistributedDataParallelTest.test_ddp_comm_hook_register_just_once
    DistributedDataParallelTest.test_ddp_invalid_comm_hook_init
    ProcessGroupGlooTest.test_round_robin
    ProcessGroupGlooTest.test_round_robin_create_destroy
distributed/test_c10d_gloo failed!
Running distributed/test_c10d_nccl ... [2023-01-12 07:43:41.085197]

ValueError: For each axis slice, the sum of the observed frequencies must agree with the sum of the expected frequencies to a relative tolerance of 1e-08, but the percent differences are:
4.535600093557479e-05

----------------------------------------------------------------------
Ran 216 tests in 22.396s

FAILED (errors=4)
distributions/test_distributions failed!

Running test_autograd ... [2023-01-13 04:19:25.587981]
Executing ['/software/Python/3.9.6-GCCcore-11.2.0/bin/python', 'test_autograd.py', '-v'] ... [2023-01-13 04:19:25.588074]
...
test_autograd_views_codegen (__main__.TestAutograd) ... ok
...
======================================================================
FAIL: test_thread_shutdown (__main__.TestAutograd)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/tmp/vsc40023/easybuild_build/PyTorch/1.11.0/foss-2021b/pytorch-v1.11.0/test/test_autograd.py", line 4220, in test_thread_shutdown
    self.assertRegex(s, "PYTORCH_API_USAGE torch.autograd.thread_shutdown")
AssertionError: Regex didn't match: 'PYTORCH_API_USAGE torch.autograd.thread_shutdown' not found in 'PYTORCH_API_USAGE torch.python.import\nPYTORCH_API_USAGE c10d.python.import\nPYTORCH_API_USAGE tensor.create\n'
----------------------------------------------------------------------
Ran 464 tests in 18.443s

FAILED (failures=1, skipped=52, expected failures=1)
test_autograd failed!
Running test_binary_ufuncs ... [2023-01-12 09:02:45.049490]
...

Running test_jit_cuda_fuser ... [2023-01-12 04:04:08.949222]
Executing ['/software/Python/3.9.6-GCCcore-11.2.0/bin/python', 'test_jit_cuda_fuser.py', '-v'] ... [2023-01-12 04:04:08.949319]
CUDA not available, skipping tests
monkeytype is not installed. Skipping tests for Profile-Directed Typing
Traceback (most recent call last):
  File "/tmp/easybuild_build/PyTorch/1.11.0/foss-2021b/pytorch-v1.11.0/test/test_jit_cuda_fuser.py", line 25, in <module>
    CUDA_MAJOR, CUDA_MINOR = (int(x) for x in torch.version.cuda.split('.'))
AttributeError: 'NoneType' object has no attribute 'split'
test_jit_cuda_fuser failed!
...
Running distributions/test_constraints ... [2023-01-12 09:05:15.013470]
SKIPPED [2] distributions/test_constraints.py:83: `biject_to` not implemented.
FAILED distributions/test_constraints.py::test_constraint[True-constraint_fn5-False-value5]
FAILED distributions/test_constraints.py::test_constraint[True-constraint_fn7-True-value7]
============= 2 failed, 128 passed, 2 skipped, 2 warnings in 8.66s =============
distributions/test_constraints failed!

Running distributions/rpc/test_tensorpipe_agent ... [2023-01-12 09:06:37.093571]
...
Ran 123 tests in 7.549s

FAILED (errors=2, skipped=2)
...
test_fx failed! Received signal: SIGSEGV
"""  # noqa


class EasyBlockSpecificTest(TestCase):
    """ Baseclass for easyblock testcases """

    # initialize configuration (required for e.g. default modules_tool setting)
    eb_go = eboptions.parse_options()
    config.init(eb_go.options, eb_go.get_options_by_section('config'))
    build_options = {
        'suffix_modules_path': GENERAL_CLASS,
        'valid_module_classes': config.module_classes(),
        'valid_stops': [x[0] for x in EasyBlock.get_steps()],
    }
    config.init_build_options(build_options=build_options)
    set_tmpdir()
    del eb_go

    def setUp(self):
        """Test setup."""
        super(EasyBlockSpecificTest, self).setUp()
        self.tmpdir = tempfile.mkdtemp()

        self.orig_sys_stdout = sys.stdout
        self.orig_sys_stderr = sys.stderr
        self.orig_environ = copy.deepcopy(os.environ)

    def tearDown(self):
        """Test cleanup."""
        remove_dir(self.tmpdir)

        sys.stdout = self.orig_sys_stdout
        sys.stderr = self.orig_sys_stderr

        # restore original environment
        modify_env(os.environ, self.orig_environ, verbose=False)

        super(EasyBlockSpecificTest, self).tearDown()

    def mock_stdout(self, enable):
        """Enable/disable mocking stdout."""
        sys.stdout.flush()
        if enable:
            sys.stdout = StringIO()
        else:
            sys.stdout = self.orig_sys_stdout

    def get_stdout(self):
        """Return output captured from stdout until now."""
        return sys.stdout.getvalue()

    def test_toolchain_external_modules(self):
        """Test use of Toolchain easyblock with external modules."""

        external_modules = ['gcc/8.3.0', 'openmpi/4.0.2', 'openblas/0.3.7', 'fftw/3.3.8', 'scalapack/2.0.2']
        external_modules_metadata = {
            # all metadata for gcc/8.3.0
            'gcc/8.3.0': {
                'name': ['GCC'],
                'version': ['8.3.0'],
                'prefix': '/software/gcc/8.3.0',
            },
            # only name/version for openmpi/4.0.2
            'openmpi/4.0.2': {
                'name': ['OpenMPI'],
                'version': ['4.0.2'],
            },
            # only name/prefix for openblas/0.3.7
            'openblas/0.3.7': {
                'name': ['OpenBLAS'],
                'prefix': '/software/openblas/0.3.7',
            },
            # only version/prefix for fftw/3.3.8 (no name)
            'fftw/3.3.8': {
                'version': ['3.3.8'],
                'prefix': '/software/fftw/3.3.8',
            },
            # no metadata for scalapack/2.0.2
        }

        # initialize configuration
        cleanup()
        eb_go = eboptions.parse_options(args=['--installpath=%s' % self.tmpdir])
        config.init(eb_go.options, eb_go.get_options_by_section('config'))
        build_options = {
            'external_modules_metadata': external_modules_metadata,
            'valid_module_classes': config.module_classes(),
        }
        config.init_build_options(build_options=build_options)
        set_tmpdir()
        del eb_go

        modtool = modules_tool()

        # make sure no $EBROOT* or $EBVERSION* environment variables are set in current environment
        for key in os.environ:
            if any(key.startswith(x) for x in ['EBROOT', 'EBVERSION']):
                del os.environ[key]

        # create dummy module file for each of the external modules
        test_mod_path = os.path.join(self.tmpdir, 'modules', 'all')
        for mod in external_modules:
            write_file(os.path.join(test_mod_path, mod), "#%Module")

        modtool.use(test_mod_path)

        # test easyconfig file to install toolchain that uses external modules,
        # and enables set_env_external_modules
        test_ec_path = os.path.join(self.tmpdir, 'test.eb')
        test_ec_txt = '\n'.join([
            "easyblock = 'Toolchain'",
            "name = 'test-toolchain'",
            "version = '1.2.3'",
            "homepage = 'https://example.com'",
            "description = 'just a test'",
            "toolchain = SYSTEM",
            "dependencies = [",
            "   ('gcc/8.3.0', EXTERNAL_MODULE),",
            "   ('openmpi/4.0.2', EXTERNAL_MODULE),",
            "   ('openblas/0.3.7', EXTERNAL_MODULE),",
            "   ('fftw/3.3.8', EXTERNAL_MODULE),",
            "   ('scalapack/2.0.2', EXTERNAL_MODULE),",
            "]",
            "set_env_external_modules = True",
            "moduleclass = 'toolchain'",
        ])
        write_file(test_ec_path, test_ec_txt)
        test_ec = process_easyconfig(test_ec_path)[0]

        # create easyblock & install module via run_all_steps
        tc_inst = get_easyblock_instance(test_ec)
        self.assertTrue(isinstance(tc_inst, Toolchain))
        self.mock_stdout(True)
        tc_inst.run_all_steps(False)
        self.mock_stdout(False)

        # make sure expected module file exists
        test_mod = os.path.join(test_mod_path, 'test-toolchain', '1.2.3')
        if get_module_syntax() == 'Lua':
            test_mod += '.lua'
        self.assertTrue(os.path.exists(test_mod))

        # load test-toolchain/1.2.3 module to get environment variable to check for defined
        modtool.load(['test-toolchain/1.2.3'])

        # check whether expected environment variables are defined
        self.assertEqual(os.environ.pop('EBROOTGCC'), '/software/gcc/8.3.0')
        self.assertEqual(os.environ.pop('EBVERSIONGCC'), '8.3.0')
        self.assertEqual(os.environ.pop('EBVERSIONOPENMPI'), '4.0.2')
        self.assertEqual(os.environ.pop('EBROOTOPENBLAS'), '/software/openblas/0.3.7')
        undefined_env_vars = [
            'EBROOTOPENMPI',  # no prefix in metadata
            'EBVERSIONOPENBLAS'  # no version in metadata
            'EBROOTFFTW', 'EBVERSIONFFTW',  # no name in metadata
            'EBROOTSCALAPACK', 'EBVERSIONSCALAPACK',  # no metadata
        ]
        for env_var in undefined_env_vars:
            self.assertTrue(os.getenv(env_var) is None)

        # make sure no unexpected $EBROOT* or $EBVERSION* environment variables were defined
        del os.environ['EBROOTTESTMINTOOLCHAIN']
        del os.environ['EBVERSIONTESTMINTOOLCHAIN']
        extra_eb_env_vars = []
        for key in os.environ:
            if any(key.startswith(x) for x in ['EBROOT', 'EBVERSION']):
                extra_eb_env_vars.append(key)
        self.assertEqual(extra_eb_env_vars, [])

    def test_det_cmake_version(self):
        """Tests for det_cmake_version function provided along with CMakeMake generic easyblock."""

        # set up fake 'cmake' command
        cmake_cmd = os.path.join(self.tmpdir, 'cmake')
        write_file(cmake_cmd, '#!/bin/bash\nexit 1')
        adjust_permissions(cmake_cmd, stat.S_IXUSR)

        os.environ['PATH'] = '%s:%s' % (self.tmpdir, os.getenv('PATH'))

        self.assertErrorRegex(EasyBuildError, "Failed to determine CMake version", det_cmake_version)

        # if $EBVERSIONCMAKE is defined (by loaded CMake module), that's picked up
        os.environ['EBVERSIONCMAKE'] = '1.2.3'
        self.assertEqual(det_cmake_version(), '1.2.3')

        del os.environ['EBVERSIONCMAKE']

        # output of 'cmake --version' as produced by CMake 2.x < 2.4.0
        write_file(cmake_cmd, textwrap.dedent("""
        #!/bin/bash
        echo "CMake version 2.3.0"
        """))
        self.assertEqual(det_cmake_version(), '2.3.0')

        # output of 'cmake --version' as produced by CMake 2.x >= 2.4.0
        write_file(cmake_cmd, textwrap.dedent("""
        #!/bin/bash
        echo "cmake version 2.4.1"
        """))
        self.assertEqual(det_cmake_version(), '2.4.1')

        # output of 'cmake --version' as produced by CMake 3.x
        write_file(cmake_cmd, textwrap.dedent("""
        #!/bin/bash
        echo "cmake version 3.15.3"
        echo ""
        echo "CMake suite maintained and supported by Kitware (kitware.com/cmake)."
        """))
        self.assertEqual(det_cmake_version(), '3.15.3')

        # also consider release candidate versions
        write_file(cmake_cmd, textwrap.dedent("""
        #!/bin/bash
        echo "cmake version 1.2.3-rc4"
        """))
        self.assertEqual(det_cmake_version(), '1.2.3-rc4')

    def test_pytorch_extract_failed_tests_info(self):
        """
        Test extract_failed_tests_info function from PyTorch easyblock.
        """
        res = pytorch.extract_failed_tests_info(PYTORCH_TESTS_OUTPUT)
        self.assertEqual(len(res), 4)

        expected_failure_report = '\n'.join([
            "distributed/fsdp/test_fsdp_input (2 total tests, failures=2)",
            "distributions/test_distributions (216 total tests, errors=4)",
            "test_autograd (464 total tests, failures=1, skipped=52, expected failures=1)",
            "test_fx (123 total tests, errors=2, skipped=2)",
            "distributions/test_constraints 2 failed, 128 passed, 2 skipped, 2 warnings",
            "distributed/test_c10d_gloo (4 failed tests)",
            "test_jit_cuda_fuser (unknown failed test count)",
        ])
        self.assertEqual(res.failure_report.strip(), expected_failure_report)
        # test failures
        self.assertEqual(res.failure_cnt, 10)
        # test errors
        self.assertEqual(res.error_cnt, 6)

        expected_failed_test_suites = [
            'distributed/fsdp/test_fsdp_input',
            'distributions/test_distributions',
            'test_autograd',
            'test_fx',
            'distributions/test_constraints',
            'distributed/test_c10d_gloo',
            'test_jit_cuda_fuser',
        ]
        self.assertEqual(res.failed_test_suites, expected_failed_test_suites)


def suite():
    """Return all easyblock-specific tests."""
    return TestLoader().loadTestsFromTestCase(EasyBlockSpecificTest)


if __name__ == '__main__':
    res = TextTestRunner(verbosity=1).run(suite())
    sys.exit(len(res.failures))
