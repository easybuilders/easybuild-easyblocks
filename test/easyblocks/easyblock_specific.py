##
# Copyright 2019-2025 Ghent University
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
from io import StringIO
from unittest import TestLoader, TextTestRunner
from test.easyblocks.module import cleanup

import easybuild.tools.options as eboptions
import easybuild.easyblocks.generic.pythonpackage as pythonpackage
from easybuild.base.testing import TestCase
from easybuild.easyblocks.generic.cmakemake import det_cmake_version
from easybuild.easyblocks.generic.toolchain import Toolchain
from easybuild.framework.easyblock import EasyBlock, get_easyblock_instance
from easybuild.framework.easyconfig.easyconfig import process_easyconfig
from easybuild.tools import config
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import GENERAL_CLASS, get_module_syntax
from easybuild.tools.environment import modify_env
from easybuild.tools.filetools import adjust_permissions, mkdir, move_file, remove_dir, symlink, write_file
from easybuild.tools.modules import modules_tool
from easybuild.tools.options import set_tmpdir


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

    def test_det_py_install_scheme(self):
        """Test det_py_install_scheme function provided by PythonPackage easyblock."""
        res = pythonpackage.det_py_install_scheme(sys.executable)
        self.assertTrue(isinstance(res, str))

        # symlink currently used python command to 'python', so we can also test det_py_install_scheme with default;
        # this is required because 'python' command may not be available
        symlink(sys.executable, os.path.join(self.tmpdir, 'python'))
        os.environ['PATH'] = '%s:%s' % (self.tmpdir, os.getenv('PATH'))

        res = pythonpackage.det_py_install_scheme()
        self.assertTrue(isinstance(res, str))

    def test_handle_local_py_install_scheme(self):
        """Test handle_local_py_install_scheme function provided by PythonPackage easyblock."""

        # test with empty dir, should be fine
        pythonpackage.handle_local_py_install_scheme(self.tmpdir)
        self.assertEqual(os.listdir(self.tmpdir), [])

        # create normal structure (no 'local' subdir), shouldn't cause trouble
        bindir = os.path.join(self.tmpdir, 'bin')
        mkdir(bindir)
        write_file(os.path.join(bindir, 'test'), 'test')
        libdir = os.path.join(self.tmpdir, 'lib')
        pyshortver = '.'.join(str(x) for x in sys.version_info[:2])
        pylibdir = os.path.join(libdir, 'python' + pyshortver, 'site-packages')
        mkdir(pylibdir, parents=True)
        write_file(os.path.join(pylibdir, 'test.py'), "import os")

        pythonpackage.handle_local_py_install_scheme(self.tmpdir)
        self.assertEqual(sorted(os.listdir(self.tmpdir)), ['bin', 'lib'])

        # move bin + lib into local/, check whether expected symlinks are created
        local_subdir = os.path.join(self.tmpdir, 'local')
        mkdir(local_subdir)
        for subdir in (bindir, libdir):
            move_file(subdir, os.path.join(local_subdir, os.path.basename(subdir)))
        self.assertEqual(os.listdir(self.tmpdir), ['local'])

        pythonpackage.handle_local_py_install_scheme(self.tmpdir)
        self.assertEqual(sorted(os.listdir(self.tmpdir)), ['bin', 'lib', 'local'])
        self.assertTrue(os.path.islink(bindir) and os.path.samefile(bindir, os.path.join(local_subdir, 'bin')))
        self.assertTrue(os.path.islink(libdir) and os.path.samefile(libdir, os.path.join(local_subdir, 'lib')))
        self.assertTrue(os.path.exists(os.path.join(bindir, 'test')))
        local_test_py = os.path.join(libdir, 'python' + pyshortver, 'site-packages', 'test.py')
        self.assertTrue(os.path.exists(local_test_py))

    def test_symlink_dist_site_packages(self):
        """Test symlink_dist_site_packages provided by PythonPackage easyblock."""
        pyshortver = '.'.join(str(x) for x in sys.version_info[:2])
        pylibdir_lib_dist = os.path.join('lib', 'python' + pyshortver, 'dist-packages')
        pylibdir_lib64_site = os.path.join('lib64', 'python' + pyshortver, 'site-packages')
        pylibdirs = [pylibdir_lib_dist, pylibdir_lib64_site]

        # first test on empty dir
        pythonpackage.symlink_dist_site_packages(self.tmpdir, pylibdirs)
        self.assertEqual(os.listdir(self.tmpdir), [])

        # check intended usage: dist-packages exists, site-packages doesn't => symlink created
        lib64_site_path = os.path.join(self.tmpdir, pylibdir_lib_dist)
        mkdir(os.path.join(self.tmpdir, pylibdir_lib_dist), parents=True)
        # also create (empty) site-packages directory, which should get replaced by a symlink to dist-packages
        mkdir(os.path.join(self.tmpdir, os.path.dirname(pylibdir_lib_dist), 'site-packages'), parents=True)

        lib64_site_path = os.path.join(self.tmpdir, pylibdir_lib64_site)
        mkdir(lib64_site_path, parents=True)
        # populate site-packages under lib64, because it'll get removed if empty
        write_file(os.path.join(lib64_site_path, 'test.py'), "import os")

        pythonpackage.symlink_dist_site_packages(self.tmpdir, pylibdirs)

        # check for expected directory structure
        self.assertEqual(sorted(os.listdir(self.tmpdir)), ['lib', 'lib64'])
        path = os.path.join(self.tmpdir, 'lib')
        self.assertEqual(os.listdir(path), ['python' + pyshortver])
        path = os.path.join(path, 'python' + pyshortver)
        self.assertEqual(sorted(os.listdir(path)), ['dist-packages', 'site-packages'])

        # check for site-packages -> dist-packages symlink
        dist_pkgs = os.path.join(path, 'dist-packages')
        self.assertTrue(os.path.isdir(dist_pkgs))
        self.assertFalse(os.path.islink(dist_pkgs))
        site_pkgs = os.path.join(path, 'site-packages')
        self.assertTrue(os.path.isdir(site_pkgs))
        self.assertTrue(os.path.islink(site_pkgs))

        # if (non-empty) site-packages dir was there, no changes were made
        lib64_path = os.path.dirname(lib64_site_path)
        self.assertEqual(sorted(os.listdir(lib64_path)), ['site-packages'])
        self.assertTrue(os.path.isdir(lib64_site_path))
        self.assertFalse(os.path.islink(lib64_site_path))


def suite(loader):
    """Return all easyblock-specific tests."""
    return loader.loadTestsFromTestCase(EasyBlockSpecificTest)


if __name__ == '__main__':
    res = TextTestRunner(verbosity=1).run(suite(TestLoader()))
    sys.exit(len(res.failures))
