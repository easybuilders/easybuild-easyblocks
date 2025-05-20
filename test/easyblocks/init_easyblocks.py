##
# Copyright 2013-2025 Ghent University
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
Unit tests for initializing easyblocks.

@author: Kenneth Hoste (Ghent University)
"""

import glob
import os
import re
import sys
import tempfile
from unittest import TestCase, TestLoader, TextTestRunner

import easybuild.tools.options as eboptions
from easybuild.base import fancylogger
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import MANDATORY
from easybuild.framework.easyconfig.easyconfig import EasyConfig, get_easyblock_class
from easybuild.framework.easyconfig.tools import get_paths_for
from easybuild.tools import config
from easybuild.tools.config import GENERAL_CLASS
from easybuild.tools.filetools import write_file
from easybuild.tools.options import set_tmpdir
# these imports are required because of checks done in template_init_test
from easybuild.tools.environment import modify_env, read_environment  # noqa
from easybuild.tools.run import parse_log_for_error, run_cmd, run_cmd_qa  # noqa


class InitTest(TestCase):
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

    def write_ec(self, easyblock, name='foo', version='1.3.2', toolchain=None, extratxt=''):
        """ create temporary easyconfig file """
        if toolchain is None:
            toolchain = 'SYSTEM'
        txt = '\n'.join([
            'easyblock = "%s"',
            'name = "%s"' % name,
            'version = "%s"' % version,
            'homepage = "http://example.com"',
            'description = "Dummy easyconfig file."',
            'toolchain = %s' % toolchain,
            'sources = []',
            extratxt,
        ])

        write_file(self.eb_file, txt % easyblock)

    def setUp(self):
        """Setup test."""
        self.log = fancylogger.getLogger("EasyblocksInitTest", fname=False)
        fd, self.eb_file = tempfile.mkstemp(prefix='easyblocks_init_test_', suffix='.eb')
        os.close(fd)

    def tearDown(self):
        """Cleanup."""
        try:
            os.remove(self.eb_file)
        except OSError as err:
            self.log.error("Failed to remove %s: %s" % (self.eb_file, err))


def template_init_test(self, easyblock, name='foo', version='1.3.2', toolchain=None, deps=None):
    """Test whether all easyblocks can be initialized."""

    def check_extra_options_format(extra_options):
        """Make sure extra_options value is of correct format."""
        # EasyBuild v2.0: dict with <string> keys and <list> values
        self.assertTrue(isinstance(extra_options, dict))
        extra_options.items()
        extra_options.keys()
        extra_options.values()
        for key in extra_options.keys():
            self.assertTrue(isinstance(extra_options[key], list))
            self.assertTrue(len(extra_options[key]), 3)
            # make sure that easyconfig parameter names do not include characters that are not allowed,
            # like dashes, to ensure that they can be defined as variables in the easyconfig file
            try:
                res = compile("%s = 1" % key, '<string>', 'exec')
            except SyntaxError:
                raise SyntaxError("Invalid easyconfig parameter name: %s" % key)

            self.assertTrue(res.co_names, (key, ))

    class_regex = re.compile(r"^class (.*)\(.*", re.M)

    self.log.debug("easyblock: %s" % easyblock)

    # read easyblock Python module
    f = open(easyblock, "r")
    txt = f.read()
    f.close()

    regexps = [
        # make sure error reporting is done correctly (no more log.error, log.exception)
        re.compile(r"log\.error\("),
        re.compile(r"log\.exception\("),
        re.compile(r"log\.raiseException\("),
    ]
    for regexp in regexps:
        self.assertFalse(regexp.search(txt), "No match for '%s' in %s" % (regexp.pattern, easyblock))

    # make sure that (named) arguments get passed down for prepare_step
    if re.search('def prepare_step', txt):
        regex = re.compile(r"def prepare_step\(self, \*args, \*\*kwargs\):")
        self.assertTrue(regex.search(txt), "Pattern '%s' found in %s" % (regex.pattern, easyblock))
    if re.search(r'\.prepare_step\(', txt):
        regex = re.compile(r"\.prepare_step\(.*\*args,.*\*\*kwargs\.*\)")
        self.assertTrue(regex.search(txt), "Pattern '%s' found in %s" % (regex.pattern, easyblock))

    # obtain easyblock class name using regex
    res = class_regex.search(txt)
    if res:
        ebname = res.group(1)
        self.log.debug("Found class name for easyblock %s: %s" % (easyblock, ebname))

        # figure out list of mandatory variables, and define with dummy values as necessary
        app_class = get_easyblock_class(ebname)
        extra_options = app_class.extra_options()
        check_extra_options_format(extra_options)

        # extend easyconfig to make sure mandatory custom easyconfig parameters are defined
        extra_txt = ''
        for (key, val) in extra_options.items():
            if val[2] == MANDATORY:
                # use default value if any is set, otherwise use "foo"
                if val[0]:
                    test_param = val[0]
                else:
                    test_param = 'foo'
                extra_txt += '%s = "%s"\n' % (key, test_param)

        if deps:
            extra_txt += 'dependencies = %s' % str(deps)

        # write easyconfig file
        self.write_ec(ebname, name=name, version=version, toolchain=toolchain, extratxt=extra_txt)

        # initialize easyblock
        # if this doesn't fail, the test succeeds
        app = app_class(EasyConfig(self.eb_file))

        # check whether easyblock instance is still using functions from a deprecated location
        mod = __import__(app.__module__, [], [], ['easybuild.easyblocks'])
        moved_functions = ['modify_env', 'parse_log_for_error', 'read_environment', 'run_cmd', 'run_cmd_qa']
        for fn in moved_functions:
            if hasattr(mod, fn):
                tup = (fn, app.__module__, globals()[fn].__module__)
                self.assertTrue(getattr(mod, fn) is globals()[fn], "%s in %s is imported from %s" % tup)

        # check whether easyblock instance is still using run_cmd or run_cmd_qa
        for fn in ('run_cmd', 'run_cmd_qa'):
            error_msg = "%s easyblock is still using %s" % (app.__module__, fn)
            error_msg += ", should be using run_shell_cmd instead"
            self.assertFalse(hasattr(mod, fn), error_msg)

        # check whether easyblock instance is using functions that have been renamed
        renamed_functions = [
            ('source_paths', 'source_path'),
            ('get_avail_core_count', 'get_core_count'),
            ('get_os_type', 'get_kernel_name'),
            ('det_full_ec_version', 'det_installversion'),
        ]
        for (new_fn, old_fn) in renamed_functions:
            self.assertFalse(hasattr(mod, old_fn), "%s: %s is replaced by %s" % (app.__module__, old_fn, new_fn))

        # cleanup
        app.close_log()
        os.remove(app.logfile)
    else:
        self.assertTrue(False, "Class found in easyblock %s" % easyblock)


def suite():
    """Return all easyblock initialisation tests."""
    def make_inner_test(easyblock, **kwargs):
        def innertest(self):
            template_init_test(self, easyblock, **kwargs)
        return innertest

    # dynamically generate a separate test for each of the available easyblocks
    easyblocks_path = get_paths_for("easyblocks")[0]
    all_pys = glob.glob('%s/*/*.py' % easyblocks_path)
    easyblocks = [eb for eb in all_pys if not eb.endswith('__init__.py') and '/test/' not in eb]

    for easyblock in easyblocks:
        easyblock_fn = os.path.basename(easyblock)
        # dynamically define new inner functions that can be added as class methods to InitTest
        if easyblock_fn == 'systemcompiler.py':
            # use GCC as name when testing SystemCompiler easyblock
            innertest = make_inner_test(easyblock, name='GCC', version='system')
        elif easyblock_fn == 'systemmpi.py':
            # use OpenMPI as name when testing SystemMPI easyblock
            innertest = make_inner_test(easyblock, name='OpenMPI', version='system')
        elif easyblock_fn in ['advisor.py', 'icc.py', 'iccifort.py', 'ifort.py', 'imkl.py', 'imkl_fftw.py',
                              'inspector.py', 'itac.py', 'tbb.py', 'vtune.py']:
            # family of IntelBase easyblocks have a minimum version support based on currently supported toolchains
            innertest = make_inner_test(easyblock, version='9999.9')
        elif easyblock_fn == 'aocc.py':
            # custom easyblock for AOCC expects a version it can map to a Clang version
            innertest = make_inner_test(easyblock, version='4.2.0')
        elif easyblock_fn == 'intel_compilers.py':
            # custom easyblock for intel-compilers (oneAPI) requires v2021.x or newer
            innertest = make_inner_test(easyblock, name='intel-compilers', version='2021.1')
        elif easyblock_fn == 'openfoam.py':
            # custom easyblock for OpenFOAM requires non-system toolchain
            innertest = make_inner_test(easyblock, toolchain={'name': 'foss', 'version': '2021a'})
        elif easyblock_fn == 'openssl_wrapper.py':
            # easyblock to create OpenSSL wrapper expects an OpenSSL version
            innertest = make_inner_test(easyblock, version='1.1')
        elif easyblock_fn == 'paraver.py':
            # custom easyblock for Paraver requires version >= 4.7
            innertest = make_inner_test(easyblock, version='4.8')
        elif easyblock_fn == 'petsc.py':
            # custom easyblock for PETSc has a minimum version requirement
            innertest = make_inner_test(easyblock, version='99.9')
        elif easyblock_fn in ['python.py', 'tkinter.py']:
            # custom easyblock for Python (ensurepip) requires version >= 3.4.0
            innertest = make_inner_test(easyblock, version='3.4.0')
        elif easyblock_fn == 'torchvision.py':
            # torchvision easyblock requires that PyTorch is listed as dependency
            innertest = make_inner_test(easyblock, name='torchvision', deps=[('PyTorch', '1.12.1')])
        else:
            innertest = make_inner_test(easyblock)

        innertest.__doc__ = "Test for initialisation of easyblock %s" % easyblock
        innertest.__name__ = "test_easyblock_%s" % '_'.join(easyblock.replace('.py', '').split('/'))
        setattr(InitTest, innertest.__name__, innertest)

    return TestLoader().loadTestsFromTestCase(InitTest)


if __name__ == '__main__':
    res = TextTestRunner(verbosity=1).run(suite())
    sys.exit(len(res.failures))
