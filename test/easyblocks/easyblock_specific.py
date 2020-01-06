##
# Copyright 2019-2020 Ghent University
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
import sys
import tempfile
from unittest import TestCase, TestLoader, TextTestRunner
from test.easyblocks.module import cleanup

import easybuild.tools.options as eboptions
from easybuild.easyblocks.generic.toolchain import Toolchain
from easybuild.framework.easyblock import get_easyblock_instance
from easybuild.framework.easyconfig.easyconfig import process_easyconfig
from easybuild.tools import config
from easybuild.tools.config import get_module_syntax
from easybuild.tools.environment import modify_env
from easybuild.tools.filetools import remove_dir, write_file
from easybuild.tools.modules import modules_tool
from easybuild.tools.options import set_tmpdir
from easybuild.tools.py2vs3 import StringIO


class EasyBlockSpecificTest(TestCase):
    """ Baseclass for easyblock testcases """

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


def suite():
    """Return all easyblock-specific tests."""
    return TestLoader().loadTestsFromTestCase(EasyBlockSpecificTest)


if __name__ == '__main__':
    res = TextTestRunner(verbosity=1).run(suite())
    sys.exit(len(res.failures))
