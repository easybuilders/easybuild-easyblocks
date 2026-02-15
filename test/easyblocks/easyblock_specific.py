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
import re
import stat
import sys
import tempfile
import textwrap
from io import StringIO
from pathlib import Path
from unittest import TestLoader, TextTestRunner
from test.easyblocks.module import cleanup

import easybuild.tools.options as eboptions
import easybuild.tools.tomllib as tomllib
import easybuild.easyblocks.generic.pythonpackage as pythonpackage
import easybuild.easyblocks.generic.cargo as cargo
import easybuild.easyblocks.l.lammps as lammps
import easybuild.easyblocks.p.python as python
import easybuild.easyblocks.p.pytorch as pytorch
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
from easybuild.tools.run import RunShellCmdResult


class EasyBlockSpecificTest(TestCase):
    """ Baseclass for easyblock testcases """

    # initialize configuration (required for e.g. default modules_tool setting)
    eb_go = eboptions.parse_options(args=[])
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
        super().setUp()
        self.tmpdir = tempfile.mkdtemp()

        self.orig_sys_stdout = sys.stdout
        self.orig_sys_stderr = sys.stderr
        self.orig_environ = copy.deepcopy(os.environ)
        self.orig_pythonpackage_run_shell_cmd = pythonpackage.run_shell_cmd

    def tearDown(self):
        """Test cleanup."""
        remove_dir(self.tmpdir)

        sys.stdout = self.orig_sys_stdout
        sys.stderr = self.orig_sys_stderr
        pythonpackage.run_shell_cmd = self.orig_pythonpackage_run_shell_cmd

        # restore original environment
        modify_env(os.environ, self.orig_environ, verbose=False)

        super().tearDown()

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

    def test_det_installed_python_packages(self):
        """
        Test det_installed_python_packages function providyed by PythonPackage easyblock
        """
        pkg1 = None
        res = python.det_installed_python_packages(python_cmd=sys.executable)
        # we can't make too much assumptions on which installed Python packages are found
        self.assertTrue(isinstance(res, list))
        if res:
            pkg1_name = res[0]
            self.assertTrue(isinstance(pkg1_name, str))

        res_detailed = python.det_installed_python_packages(python_cmd=sys.executable, names_only=False)
        self.assertTrue(isinstance(res_detailed, list))
        if res_detailed:
            pkg1 = res_detailed[0]
            self.assertTrue(isinstance(pkg1, dict))
            self.assertTrue(sorted(pkg1.keys()), ['name', 'version'])
            self.assertEqual(pkg1['name'], pkg1_name)
            regex = re.compile('^[0-9].*')
            ver = pkg1['version']
            self.assertTrue(regex.match(ver), f"Pattern {regex.pattern} matches for pkg version: {ver}")

        def mocked_run_shell_cmd_pip(cmd, **kwargs):
            stderr = None
            if "pip list" in cmd:
                output = '[{"name": "example", "version": "1.2.3"}]'
                stderr = "DEPRECATION: Python 2.7 reached the end of its life on January 1st, 2020"
            else:
                # unexpected command
                return None

            return RunShellCmdResult(cmd=cmd, exit_code=0, output=output, stderr=stderr, work_dir=None,
                                     out_file=None, err_file=None, cmd_sh=None, thread_id=None, task_id=None)
        python.run_shell_cmd = mocked_run_shell_cmd_pip
        res = python.det_installed_python_packages(python_cmd=sys.executable)
        self.assertEqual(res, ['example'])

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

    def test_cargo_get_workspace_members(self):
        """Test get_workspace_members in the Cargo easyblock"""
        # Simple crate
        toml_text = textwrap.dedent("""
            [package]
            name = 'my_crate'
            version = "0.1.0"
            edition = "2021"
            description = 'desc'
            documentation = "url"
            license = "MIT"
        """)
        members = cargo._get_workspace_members(tomllib.loads(toml_text))
        self.assertIsNone(members)

        # Virtual manifest
        toml_text = textwrap.dedent("""
            [workspace]
            members = [
                "reqwest-middleware",
                "reqwest-tracing",
                "reqwest-retry",
            ]
        """)
        members = cargo._get_workspace_members(tomllib.loads(toml_text))
        self.assertEqual(members, ["reqwest-middleware", "reqwest-tracing", "reqwest-retry"])

        # Workspace (root is a package too)
        toml_text = textwrap.dedent("""
            [package]
            name = "nothing-linux-ui"
            version = "0.0.2"
            edition = "2021"
            authors = ["sn99"]

            [workspace]
            members = ["nothing", "src-tauri"]

            [dependencies]
            leptos = { version = "0.6", features = ["csr"] }
        """)
        members = cargo._get_workspace_members(tomllib.loads(toml_text))
        self.assertEqual(members, ["nothing", "src-tauri"])

    def test_cargo_merge_sub_crate(self):
        """Test merge_sub_crate in the Cargo easyblock"""
        crate_dir = Path(tempfile.mkdtemp())
        cargo_toml = crate_dir / 'Cargo.toml'
        ws_parsed = tomllib.loads("""
            [workspace]
            members = ["bar"]

            [workspace.package]
            version = "1.2.3"
            authors = ["Nice Folks"]
            description = "A short description of my package"
            documentation = "https://example.com/bar"

            [workspace.dependencies]
            regex = { version = "1.6.0", default-features = false, features = ["std"] }
            cc = "1.0.73"
            rand = "0.8.5"

            [workspace.lints.rust]
            unsafe_code = "forbid"
        """)
        cargo_toml.write_text("""
            [package]
            name = "bar"
            version.workspace = true
            authors.workspace = true
            description.workspace = true
            documentation.workspace = true

            # Unrelated line that looks like a workspace key
            dummy = "Uses regex=123 and regex = 456 and not foo.workspace = true"

            [dependencies]
            foo = { version = "42" }
            # Overwrite 'features' value
            regex = { workspace = true, features = ["unicode"] }

            [build-dependencies]
            cc.workspace = true

            [dev-dependencies]
            rand = { workspace = true }

            [lints]
            workspace = true
        """)
        cargo._merge_sub_crate(cargo_toml, ws_parsed)
        self.assertEqual(tomllib.loads(cargo_toml.read_text()), tomllib.loads("""
            [package]
            name = "bar"
            version = "1.2.3"
            authors = ["Nice Folks"]
            description = "A short description of my package"
            documentation = "https://example.com/bar"

            dummy = "Uses regex=123 and regex = 456 and not foo.workspace = true"

            [dependencies]
            foo = { version = "42" }
            regex = { version = "1.6.0", default-features = false, features = ["unicode"] }

            [build-dependencies]
            cc = "1.0.73"

            [dev-dependencies]
            rand = "0.8.5"

            [lints.rust]
            unsafe_code = "forbid"
        """))

        # Only dict-style workspace dependency
        cargo_toml.write_text("""
            [package]
            name = "bar"

            [dependencies]
            regex = { workspace = true }
        """)
        cargo._merge_sub_crate(cargo_toml, ws_parsed)
        self.assertEqual(tomllib.loads(cargo_toml.read_text()), tomllib.loads("""
            [package]
            name = "bar"

            [dependencies]
            regex = { version = "1.6.0", default-features = false, features = ["std"] }
        """))

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

    def test_run_pip_check(self):
        """Test run_pip_check function provided by EB_Python easyblock."""

        def mocked_run_shell_cmd_pip(cmd, **kwargs):
            if "pip check" in cmd:
                output = "No broken requirements found."
            elif "pip --version" in cmd:
                output = "pip 20.0"
            else:
                # unexpected command
                return None

            return RunShellCmdResult(cmd=cmd, exit_code=0, output=output, stderr=None, work_dir=None,
                                     out_file=None, err_file=None, cmd_sh=None, thread_id=None, task_id=None)

        python.run_shell_cmd = mocked_run_shell_cmd_pip
        with self.mocked_stdout_stderr():
            python.run_pip_check(python_cmd=sys.executable)

        # inject all possible errors
        def mocked_run_shell_cmd_pip(cmd, **kwargs):
            if "pip check" in cmd:
                output = "foo-1.2.3 requires bar-4.5.6, which is not installed."
                exit_code = 1
            elif "pip --version" in cmd:
                output = "pip 20.0"
                exit_code = 0
            else:
                # unexpected command
                return None

            return RunShellCmdResult(cmd=cmd, exit_code=exit_code, output=output, stderr=None, work_dir=None,
                                     out_file=None, err_file=None, cmd_sh=None, thread_id=None, task_id=None)

        python.run_shell_cmd = mocked_run_shell_cmd_pip
        error_pattern = '\n'.join([
            "pip check.*failed.*",
            "foo.*requires.*bar.*not installed.*",
        ])
        with self.mocked_stdout_stderr():
            self.assertErrorRegex(EasyBuildError, error_pattern, python.run_pip_check,
                                  python_cmd=sys.executable)

        # invalid pip version
        def mocked_run_shell_cmd_pip(cmd, **kwargs):
            return RunShellCmdResult(cmd=cmd, exit_code=0, output="1.2.3", stderr=None, work_dir=None,
                                     out_file=None, err_file=None, cmd_sh=None, thread_id=None, task_id=None)

        python.run_shell_cmd = mocked_run_shell_cmd_pip
        error_pattern = "Failed to determine pip version!"
        self.assertErrorRegex(EasyBuildError, error_pattern, python.run_pip_check, python_cmd=sys.executable)

    def test_run_pip_list(self):
        """Test run_pip_list function provided by EB_Python easyblock."""

        def mocked_run_shell_cmd_pip(cmd, **kwargs):
            if "pip list" in cmd:
                output = '[{"name": "example", "version": "1.2.3"}]'
            else:
                # unexpected command
                return None

            return RunShellCmdResult(cmd=cmd, exit_code=0, output=output, stderr=None, work_dir=None,
                                     out_file=None, err_file=None, cmd_sh=None, thread_id=None, task_id=None)

        python.run_shell_cmd = mocked_run_shell_cmd_pip
        with self.mocked_stdout_stderr():
            python.run_pip_list([], python_cmd=sys.executable)

        # test ignored unversioned Python packages
        def mocked_run_shell_cmd_pip(cmd, **kwargs):
            if "pip list" in cmd:
                output = '[{"name": "zero", "version": "0.0.0"}, {"name": "example-pkg", "version": "1.2.3"}]'
            else:
                # unexpected command
                return None

            return RunShellCmdResult(cmd=cmd, exit_code=0, output=output, stderr=None, work_dir=None,
                                     out_file=None, err_file=None, cmd_sh=None, thread_id=None, task_id=None)

        python.run_shell_cmd = mocked_run_shell_cmd_pip
        with self.mocked_stdout_stderr():
            python.run_pip_list([('example_pkg', '1.2.3')], python_cmd=sys.executable, unversioned_packages=('zero', ))

        with self.mocked_stdout_stderr():
            python.run_pip_list([('example.pkg', '1.2.3')], python_cmd=sys.executable, unversioned_packages={'zero'})

        # inject all possible errors with unversioned packages
        def mocked_run_shell_cmd_pip(cmd, **kwargs):
            if "pip list" in cmd:
                output = '[{"name": "example", "version": "1.2.3"}, {"name": "wrong", "version": "0.0.0"}]'
                exit_code = 0
            else:
                # unexpected command
                return None

            return RunShellCmdResult(cmd=cmd, exit_code=exit_code, output=output, stderr=None, work_dir=None,
                                     out_file=None, err_file=None, cmd_sh=None, thread_id=None, task_id=None)

        python.run_shell_cmd = mocked_run_shell_cmd_pip
        error_pattern = '\n'.join([
            r"Package 'example'.*version of 1\.2\.3 which is valid.*",
            "Package 'nosuchpkg' in unversioned_packages was not found in the installed packages.*",
            r".*not installed correctly.*version of '0\.0\.0':",
            "wrong",
        ])
        with self.mocked_stdout_stderr():
            self.assertErrorRegex(EasyBuildError, error_pattern, python.run_pip_list, [],
                                  python_cmd=sys.executable, unversioned_packages=['example', 'nosuchpkg'])

        # inject errors with mismatched packages name or version
        def mocked_run_shell_cmd_pip(cmd, **kwargs):
            if "pip list" in cmd:
                output = '[{"name": "example", "version": "1.2.3"}, {"name": "wrong-version", "version": "1.1.1"}]'
                exit_code = 0
            else:
                # unexpected command
                return None

            return RunShellCmdResult(cmd=cmd, exit_code=exit_code, output=output, stderr=None, work_dir=None,
                                     out_file=None, err_file=None, cmd_sh=None, thread_id=None, task_id=None)

        python.run_shell_cmd = mocked_run_shell_cmd_pip
        error_pattern = '\n'.join([
            r"The following Python packages were likely specified with a wrong name because they are missing",
            r"wrong-name",
            r"The following Python packages were likely specified with a wrong version",
            r"wrong-version 5.6.7",
        ])
        with self.mocked_stdout_stderr():
            self.assertErrorRegex(EasyBuildError, error_pattern, python.run_pip_list,
                                  [('wrong_name', '1.2.3'), ('wrong_version', '5.6.7')],
                                  python_cmd=sys.executable)

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

    def test_translate_lammps_version(self):
        """Test translate_lammps_version function from LAMMPS easyblock"""
        lammps_versions = {
            '23Jun2022': '2022.06.23',
            '2Aug2023_update2': '2023.08.02.2',
            '29Aug2024': '2024.08.29',
            '29Aug2024_update2': '2024.08.29.2',
            '28Oct2024': '2024.10.28',
        }
        for key, expected_version in lammps_versions.items():
            self.assertEqual(lammps.translate_lammps_version(key), expected_version)

        version_file = os.path.join(self.tmpdir, 'src', 'version.h')
        version_txt = '\n'.join([
            '#define LAMMPS_VERSION "2 Apr 2025"',
            '#define LAMMPS_UPDATE "Development"',
        ])
        write_file(version_file, version_txt)

        self.assertEqual(lammps.translate_lammps_version('d3adb33f', path=self.tmpdir), '2025.04.02')
        self.assertEqual(lammps.translate_lammps_version('devel', path=self.tmpdir), '2025.04.02')

        version_file = os.path.join(self.tmpdir, 'src', 'version.h')
        version_txt = '\n'.join([
            '#define LAMMPS_VERSION "2 Apr 2025"',
            '#define LAMMPS_UPDATE "Update 3"',
        ])
        write_file(version_file, version_txt)

        self.assertEqual(lammps.translate_lammps_version('d3adb33f', path=self.tmpdir), '2025.04.02.3')

    def test_pytorch_test_log_parsing(self):
        """Verify parsing of XML files produced by PyTorch tests."""
        TestState = pytorch.TestState

        test_log_dir = Path(__file__).parent.parent / 'pytorch_test_logs'

        results = pytorch.get_test_results(test_log_dir / 'test-reports')
        results2 = pytorch.get_test_results(test_log_dir)
        self.assertEqual(results.keys(), results2.keys())
        for name, suite in results.items():
            self.assertEqual((name, suite.summary), (name, results2[name].summary))
        del results2

        self.assertEqual(len(results), 15)

        # 2 small test suites used as a smoke test using a most features
        self.assertIn('backends/xeon/test_launch', results)
        suite = results['backends/xeon/test_launch']
        self.assertEqual((suite.errors, suite.failures, suite.num_tests, suite.skipped), (1, 2, 8, 3))
        # Failure in one file, success in the other --> Success
        self.assertEqual(suite['TestTorchrun.test_cpu_info'].state, TestState.SUCCESS)
        # New in 2nd file
        self.assertEqual(suite['TestTorchrun.test_multi_threads'].state, TestState.SUCCESS)
        self.assertEqual(suite['TestTorchrun.test_reshape_cpu_float64'].state, TestState.FAILURE)
        self.assertEqual(suite['TestTorchrun.test_foo'].state, TestState.SKIPPED)
        self.assertEqual(suite['TestTorchrun.test_bar'].state, TestState.ERROR)
        self.assertEqual(suite.get_errored_tests(), ['TestTorchrun.test_bar'])
        self.assertEqual(suite.get_failed_tests(), ['TestTorchrun.test_reshape_cpu_float64', 'TestTorchrun.test_baz'])
        self.assertIn('test_autoload', results)
        suite = results['test_autoload']
        self.assertEqual((suite.errors, suite.failures, suite.num_tests, suite.skipped), (0, 0, 2, 1))
        self.assertEqual(suite['TestBackendAutoload.test_autoload'].state, TestState.SUCCESS)
        self.assertEqual(suite['TestBackendAutoload.test_unload'].state, TestState.SKIPPED)

        # Verify summaries which should be enough to catch most issues
        report = '\n'.join(sorted(f'{suite.name}: {suite.summary}' for suite in results.values()))
        self.assertEqual(report, textwrap.dedent("""
            backends/xeon/test_launch: 2 failed, 2 passed, 3 skipped, 1 errors
            dist-gloo-init-env/distr/algorithms/quantization/test_quantization: 0 failed, 1 passed, 0 skipped, 0 errors
            dist-gloo-init-file/distr/algorithms/quantization/test_quantization: 0 failed, 1 passed, 0 skipped, 0 errors
            dist-nccl-init-env/distr/algorithms/quantization/test_quantization: 0 failed, 1 passed, 0 skipped, 0 errors
            dist-nccl-init-file/distr/algorithms/quantization/test_quantization: 0 failed, 1 passed, 0 skipped, 0 errors
            dist/foo/bar: 0 failed, 4 passed, 0 skipped, 0 errors
            distributed/tensor/test_dtensor_ops: 0 failed, 2 passed, 2 skipped, 0 errors
            dynamo/test_dynamic_shapes: 3 failed, 14 passed, 0 skipped, 0 errors
            dynamo/test_misc: 1 failed, 9 passed, 0 skipped, 0 errors
            inductor/test_aot_inductor_arrayref: 2 failed, 0 passed, 0 skipped, 0 errors
            inductor/test_cudagraph_trees: 1 failed, 0 passed, 0 skipped, 0 errors
            jit/test_builtins: 0 failed, 1 passed, 0 skipped, 0 errors
            test_autoload: 0 failed, 1 passed, 1 skipped, 0 errors
            test_nestedtensor: 3 failed, 2 passed, 3 skipped, 1 errors
            test_quantization: 0 failed, 12 passed, 5 skipped, 0 errors
        """).strip())
        tests = '\n'.join(sorted(f'{test.name}: {test.state.value}'
                                 for suite in results.values()
                                 for test in suite.get_tests()))
        self.assertEqual(tests, textwrap.dedent("""
            AOTInductorTestABICompatibleCpuWithStackAllocation.test_fail_and_skip: failure
            AOTInductorTestABICompatibleCpuWithStackAllocation.test_skip_and_fail: failure
            CudaGraphTreeTests.test_workspace_allocation_error: failure
            DistQuantizationTests.test_all_gather_fp16: success
            DistQuantizationTests.test_all_gather_fp16: success
            DistQuantizationTests.test_all_gather_fp16: success
            DistQuantizationTests.test_all_gather_fp16: success
            DynamicShapesCtxManagerTests.test_autograd_profiler_dynamic_shapes: success
            DynamicShapesCtxManagerTests.test_generic_context_manager_with_graph_break_dynamic_shapes: success
            DynamicShapesCtxManagerTests.test_generic_ctx_manager_with_graph_break_dynamic_shapes: success
            DynamicShapesMiscTests.test_outside_linear_module_free_dynamic_shapes: failure
            DynamicShapesMiscTests.test_packaging_version_parse_dynamic_shapes: success
            DynamicShapesMiscTests.test_pair_dynamic_shapes: success
            DynamicShapesMiscTests.test_param_shape_binops_dynamic_shapes: success
            DynamicShapesMiscTests.test_parameter_free_dynamic_shapes: failure
            DynamicShapesMiscTests.test_patched_builtin_functions_dynamic_shapes: success
            DynamicShapesMiscTests.test_proxy_frozen_dataclass_dynamic_shapes: success
            DynamicShapesMiscTests.test_pt2_compliant_ops_are_allowed_dynamic_shapes: success
            DynamicShapesMiscTests.test_pt2_compliant_overload_dynamic_shapes: success
            DynamicShapesMiscTests.test_pure_python_accumulate_dynamic_shapes: success
            DynamicShapesMiscTests.test_py_guards_mark_dynamic_dynamic_shapes: success
            DynamicShapesMiscTests.test_python_slice_dynamic_shapes: success
            DynamicShapesMiscTests.test_pytree_tree_flatten_unflatten_dynamic_shapes: success
            DynamicShapesMiscTests.test_pytree_tree_leaves_dynamic_shapes: failure
            MiscTests.test_packaging_version_parse: success
            MiscTests.test_pair: success
            MiscTests.test_param_shape_binops: success
            MiscTests.test_parameter_free: failure
            MiscTests.test_pytree_tree_map: success
            MiscTests.test_shape_env_no_recording: success
            MiscTests.test_shape_env_recorded_function_fallback: success
            MiscTests.test_yield_from_in_a_loop: success
            TestBackendAutoload.test_autoload: success
            TestBackendAutoload.test_unload: skipped
            TestBuiltins.test_name: success
            TestCustomFunction.test_autograd_function_with_matmul_folding_at_output: success
            TestDTensorOpsCPU.test_dtensor_op_db_H_cpu_float16: success
            TestDTensorOpsCPU.test_dtensor_op_db_H_cpu_float32: success
            TestDTensorOpsCPU.test_dtensor_op_db_H_cpu_float64: skipped
            TestDTensorOpsCPU.test_dtensor_op_db_H_cpu_int8: skipped
            TestDynamicQuantizedOps.test_qrnncell: success
            TestFakeQuantizeOps.test_backward_per_channel: skipped
            TestFakeQuantizeOps.test_backward_per_channel_cachemask_cpu: success
            TestFakeQuantizeOps.test_backward_per_channel_cachemask_cuda: success
            TestName.test_bar: success
            TestNestedTensor.test_bmm_cuda_gpu_float16: failure
            TestNestedTensor.test_bmm_cuda_gpu_float32: failure
            TestNestedTensor.test_bmm_cuda_gpu_float64: error
            TestNestedTensor.test_cat: success
            TestNestedTensor.test_copy_: success
            TestNestedTensor.test_reshape_cpu_float16: skipped
            TestNestedTensor.test_reshape_cpu_float32: skipped
            TestNestedTensor.test_reshape_cpu_float64: failure
            TestNestedTensorSubclassCPU.test_linear_backward_memory_usage_cpu_float32: skipped
            TestNumericDebugger.test_quantize_pt2e_preserve_handle: success
            TestNumericDebugger.test_re_export_preserve_handle: success
            TestPadding.test_reflection_pad1d: success
            TestQuantizedConv.test_conv_reorder_issue_onednn: success
            TestQuantizedConv.test_conv_transpose_reorder_issue_onednn: success
            TestQuantizedFunctionalOps.test_relu_api: success
            TestQuantizedLinear.test_qlinear_cudnn: skipped
            TestQuantizedLinear.test_qlinear_gelu_pt2e: success
            TestQuantizedOps.test_adaptive_avg_pool2d_nhwc: success
            TestQuantizedOps.test_adaptive_avg_pool: skipped
            TestQuantizedOps.test_qadd_relu_cudnn: skipped
            TestQuantizedOps.test_qadd_relu_cudnn_nhwc: skipped
            TestQuantizedOps.test_qadd_relu_different_qparams: success
            TestTorchrun.test_bar: error
            TestTorchrun.test_baz: failure
            TestTorchrun.test_cpu_info: success
            TestTorchrun.test_foo2: skipped
            TestTorchrun.test_foo3: skipped
            TestTorchrun.test_foo: skipped
            TestTorchrun.test_multi_threads: success
            TestTorchrun.test_reshape_cpu_float64: failure
            TestTracer.test_jit_save: success
            bar.test_2.test_func3: success
            bar.test_foo.TestBar.test_func2: success
            bar.test_foo.TestName.test_func1: success
        """).strip())

        #  Some error cases
        error_log_dir = test_log_dir / 'faulty-reports'

        self.assertErrorRegex(ValueError, "<testsuites> or <testsuite>",
                              pytorch.get_test_results, error_log_dir / 'root')
        self.assertErrorRegex(ValueError, "Failed to parse",
                              pytorch.get_test_results, error_log_dir / 'invalid_xml')
        self.assertErrorRegex(ValueError, "multiple reported files",
                              pytorch.get_test_results, error_log_dir / 'multi_file')
        self.assertErrorRegex(ValueError, "Path from folder and filename should be equal",
                              pytorch.get_test_results, error_log_dir / 'different_file_name')
        self.assertErrorRegex(ValueError, "Unexpected file attribute",
                              pytorch.get_test_results, error_log_dir / 'file_attribute')
        self.assertErrorRegex(ValueError, "Invalid state",
                              pytorch.get_test_results, error_log_dir / 'skip_and_failed')
        self.assertErrorRegex(ValueError, "no test",
                              pytorch.get_test_results, error_log_dir / 'no_tests')
        self.assertErrorRegex(ValueError, "Invalid test count",
                              pytorch.get_test_results, error_log_dir / 'consistency')
        self.assertErrorRegex(ValueError, "Duplicate test",
                              pytorch.get_test_results, error_log_dir / 'duplicate')


def suite(loader):
    """Return all easyblock-specific tests."""
    return loader.loadTestsFromTestCase(EasyBlockSpecificTest)


if __name__ == '__main__':
    res = TextTestRunner(verbosity=1).run(suite(TestLoader()))
    sys.exit(len(res.failures))
