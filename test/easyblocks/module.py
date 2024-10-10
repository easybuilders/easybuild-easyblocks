##
# Copyright 2015-2024 Ghent University
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
Unit tests to check that easyblocks are compatible with --module-only.

@author: Kenneth Hoste (Ghent University)
"""
import copy
import glob
import os
import re
import stat
import sys
import tempfile
from unittest import TestLoader, TextTestRunner

import easybuild.tools.module_naming_scheme.toolchain as mns_toolchain
import easybuild.tools.options as eboptions
import easybuild.tools.toolchain.utilities as tc_utils
from easybuild.base import fancylogger
from easybuild.base.testing import TestCase
from easybuild.easyblocks.generic.gopackage import GoPackage
from easybuild.easyblocks.generic.juliabundle import JuliaBundle
from easybuild.easyblocks.generic.juliapackage import JuliaPackage
from easybuild.easyblocks.generic.intelbase import IntelBase
from easybuild.easyblocks.generic.pythonbundle import PythonBundle
from easybuild.easyblocks.generic.cargopythonbundle import CargoPythonBundle
from easybuild.easyblocks.gcc import EB_GCC
from easybuild.easyblocks.elpa import EB_ELPA
from easybuild.easyblocks.fftw import EB_FFTW
from easybuild.easyblocks.fftwmpi import EB_FFTW_period_MPI
from easybuild.easyblocks.imkl_fftw import EB_imkl_minus_FFTW
from easybuild.easyblocks.openfoam import EB_OpenFOAM
from easybuild.framework.easyconfig import easyconfig
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import MANDATORY
from easybuild.framework.easyconfig.easyconfig import EasyConfig, get_easyblock_class
from easybuild.framework.easyconfig.tools import get_paths_for
from easybuild.tools import config
from easybuild.tools.config import GENERAL_CLASS, Singleton
from easybuild.tools.filetools import adjust_permissions, change_dir, mkdir, read_file, remove_dir
from easybuild.tools.filetools import remove_file, write_file
from easybuild.tools.modules import get_software_root_env_var_name, get_software_version_env_var_name
from easybuild.tools.options import set_tmpdir


# partial output of actual 'ucx_info -b'
FAKE_UCX_INFO = """#!/bin/bash
echo '#define UCX_CONFIG_H'
echo '#define HAVE_IB                   1'
echo '#define HAVE_MEMALIGN             1'
echo '#define PACKAGE                   "ucx"'
echo '#define PACKAGE_VERSION           "1.10"'
echo '#define VERSION                   "1.10"'
echo '#define test_MODULES              ":module"'
echo '#define ucm_MODULES               ""'
echo '#define uct_MODULES               ":ib:rdmacm:cma"'
echo '#define uct_cuda_MODULES          ""'
echo '#define uct_ib_MODULES            ""'
echo '#define uct_rocm_MODULES          ""'
echo '#define ucx_perftest_MODULES      ""'
echo '#define UCX_MODULE_SUBDIR         "ucx"'
echo '#define test_MODULES              ":module"'
echo '#define ucm_MODULES               ""'
echo '#define uct_MODULES               ":ib:rdmacm:cma"'
echo '#define uct_cuda_MODULES          ""'
echo '#define uct_ib_MODULES            ""'
echo '#define uct_rocm_MODULES          ""'
echo '#define ucx_perftest_MODULES      ""'
"""

TMPDIR = tempfile.mkdtemp()


def cleanup():
    """Perform cleanup of singletons and caches."""
    # clear Singelton instances, to start afresh
    Singleton._instances.clear()

    # empty caches
    tc_utils._initial_toolchain_instances.clear()
    easyconfig._easyconfigs_cache.clear()
    easyconfig._easyconfig_files_cache.clear()
    mns_toolchain._toolchain_details_cache.clear()


def install_fake_command(cmd, cmd_script, tmpdir):
    """Install fake command with given name and script."""
    cmd_path = os.path.join(tmpdir, cmd)
    write_file(cmd_path, cmd_script)
    adjust_permissions(cmd_path, stat.S_IXUSR)
    os.environ['PATH'] = os.pathsep.join([tmpdir, os.getenv('PATH')])


class ModuleOnlyTest(TestCase):
    """ Baseclass for easyblock testcases """

    def writeEC(self, easyblock, name='foo', version='1.3.2', extratxt='', toolchain=None):
        """ create temporary easyconfig file """
        if toolchain is None:
            toolchain = {'name': 'system', 'version': 'system'}

        txt = '\n'.join([
            'easyblock = "%s"',
            'name = "%s"' % name,
            'version = "%s"' % version,
            'homepage = "http://example.com"',
            'description = "Dummy easyconfig file."',
            "toolchain = {'name': '%(name)s', 'version': '%(version)s'}" % toolchain,
            'sources = []',
            extratxt,
        ])

        write_file(self.eb_file, txt % easyblock)

    def setUp(self):
        """Setup test."""
        super(ModuleOnlyTest, self).setUp()

        self.log = fancylogger.getLogger("EasyblocksModuleOnlyTest", fname=False)
        fd, self.eb_file = tempfile.mkstemp(prefix='easyblocks_module_only_test_', suffix='.eb')
        os.close(fd)

        self.orig_environ = copy.deepcopy(os.environ)

    def tearDown(self):
        """Clean up after running test."""
        super(ModuleOnlyTest, self).tearDown()

        os.environ = self.orig_environ

        remove_file(self.eb_file)

    def test_make_module_pythonpackage(self):
        """Test make_module_step of PythonPackage easyblock."""
        app_class = get_easyblock_class('PythonPackage')
        self.writeEC('PythonPackage', name='testpypkg', version='3.14')
        app = app_class(EasyConfig(self.eb_file))

        # install dir should not be there yet
        self.assertFalse(os.path.exists(app.installdir), "%s should not exist" % app.installdir)

        # create install dir and populate it with subdirs/files
        mkdir(app.installdir, parents=True)
        # $PATH, $LD_LIBRARY_PATH, $LIBRARY_PATH, $CPATH, $PKG_CONFIG_PATH
        write_file(os.path.join(app.installdir, 'bin', 'foo'), 'echo foo!')
        write_file(os.path.join(app.installdir, 'include', 'foo.h'), 'bar')
        write_file(os.path.join(app.installdir, 'lib', 'libfoo.a'), 'libfoo')
        pyver = '.'.join(map(str, sys.version_info[:2]))
        write_file(os.path.join(app.installdir, 'lib', 'python%s' % pyver, 'site-packages', 'foo.egg'), 'foo egg')
        write_file(os.path.join(app.installdir, 'lib64', 'pkgconfig', 'foo.pc'), 'libfoo: foo')

        # PythonPackage relies on the fact that 'python' points to the right Python version
        tmpdir = tempfile.mkdtemp()
        python = os.path.join(tmpdir, 'python')
        write_file(python, '#!/bin/bash\necho $0 $@\n%s "$@"' % sys.executable)
        adjust_permissions(python, stat.S_IXUSR)
        os.environ['PATH'] = '%s:%s' % (tmpdir, os.getenv('PATH', ''))

        from easybuild.tools.filetools import which
        print(which('python'))

        # create module file
        with self.mocked_stdout_stderr():
            app.make_module_step()

        remove_file(python)

        self.assertTrue(TMPDIR in app.installdir)
        self.assertTrue(TMPDIR in app.installdir_mod)

        modtxt = None
        for cand_mod_filename in ['3.14', '3.14.lua']:
            full_modpath = os.path.join(app.installdir_mod, 'testpypkg', cand_mod_filename)
            if os.path.exists(full_modpath):
                modtxt = read_file(full_modpath)
                break

        self.assertFalse(modtxt is None)

        regexs = [
            (r'^prepend.path.*\WCPATH\W.*include"?\W*$', True),
            (r'^prepend.path.*\WLD_LIBRARY_PATH\W.*lib"?\W*$', True),
            (r'^prepend.path.*\WLIBRARY_PATH\W.*lib"?\W*$', True),
            (r'^prepend.path.*\WPATH\W.*bin"?\W*$', True),
            (r'^prepend.path.*\WPKG_CONFIG_PATH\W.*lib64/pkgconfig"?\W*$', True),
            (r'^prepend.path.*\WPYTHONPATH\W.*lib/python[23]\.[0-9]+/site-packages"?\W*$', True),
            # lib64 doesn't contain any library files, so these are *not* included in $LD_LIBRARY_PATH or $LIBRARY_PATH
            (r'^prepend.path.*\WLD_LIBRARY_PATH\W.*lib64', False),
            (r'^prepend.path.*\WLIBRARY_PATH\W.*lib64', False),
        ]
        for (pattern, found) in regexs:
            regex = re.compile(pattern, re.M)
            if found:
                assert_msg = "Pattern '%s' found in: %s" % (regex.pattern, modtxt)
            else:
                assert_msg = "Pattern '%s' not found in: %s" % (regex.pattern, modtxt)

            self.assertEqual(bool(regex.search(modtxt)), found, assert_msg)

    def test_pythonpackage_det_pylibdir(self):
        """Test det_pylibdir function from pythonpackage.py."""
        from easybuild.easyblocks.generic.pythonpackage import det_pylibdir
        for pylibdir in [det_pylibdir(), det_pylibdir(plat_specific=True), det_pylibdir(python_cmd=sys.executable)]:
            self.assertTrue(pylibdir.startswith('lib') and '/python' in pylibdir and pylibdir.endswith('site-packages'))

    def test_pythonpackage_pick_python_cmd(self):
        """Test pick_python_cmd function from pythonpackage.py."""
        from easybuild.easyblocks.generic.pythonpackage import pick_python_cmd
        self.assertIsNotNone(pick_python_cmd())
        self.assertIsNotNone(pick_python_cmd(3))
        self.assertIsNotNone(pick_python_cmd(3, 6))
        self.assertIsNone(pick_python_cmd(123, 456))
        self.assertIsNotNone(pick_python_cmd(2, 6, 123, 456))
        self.assertIsNotNone(pick_python_cmd(2, 6, 2))
        self.assertIsNone(pick_python_cmd(2, 6, 1, 1))
        maj_ver, min_ver = sys.version_info[0:2]
        self.assertIsNotNone(pick_python_cmd(maj_ver, min_ver))
        self.assertIsNotNone(pick_python_cmd(maj_ver, min_ver, max_py_majver=maj_ver))
        self.assertIsNotNone(pick_python_cmd(maj_ver, min_ver, max_py_majver=maj_ver, max_py_minver=min_ver))
        self.assertIsNotNone(pick_python_cmd(maj_ver, min_ver, max_py_majver=maj_ver, max_py_minver=min_ver + 1))
        self.assertIsNone(pick_python_cmd(maj_ver, min_ver, max_py_majver=maj_ver - 1))
        self.assertIsNone(pick_python_cmd(maj_ver, min_ver, max_py_majver=maj_ver, max_py_minver=min_ver - 1))


def template_module_only_test(self, easyblock, name, version='1.3.2', extra_txt='', tmpdir=None):
    """Test whether all easyblocks are compatible with --module-only."""

    if tmpdir is None:
        tmpdir = tempfile.mkdtemp()

    class_regex = re.compile(r"^class (.*)\(.*", re.M)

    self.log.debug("easyblock: %s" % easyblock)

    # read easyblock Python module
    f = open(easyblock, "r")
    txt = f.read()
    f.close()

    # obtain easyblock class name using regex
    res = class_regex.search(txt)
    if res:
        ebname = res.group(1)
        self.log.debug("Found class name for easyblock %s: %s" % (easyblock, ebname))

        toolchain = None

        # figure out list of mandatory variables, and define with dummy values as necessary
        app_class = get_easyblock_class(ebname)

        # easyblocks deriving from IntelBase require a license file to be found for --module-only
        bases = list(app_class.__bases__)
        for base in copy.copy(bases):
            bases.extend(base.__bases__)

        if app_class == EB_FFTW_period_MPI:
            # $EBROOTFFTW must be set for FFTW.MPI, because of dependency check on FFTW in prepare_step
            os.environ['EBROOTFFTW'] = '/fake/software/FFTW/3.3.10'

        if app_class == EB_imkl_minus_FFTW:
            # $EBROOTIMKL must be set for imkl-FFTW, because of dependency check on imkl in prepare_step
            os.environ['EBROOTIMKL'] = '/fake/software/imkl/2021.4.0/mkl/2021.4.0'

        if app_class == IntelBase or IntelBase in bases:
            os.environ['INTEL_LICENSE_FILE'] = os.path.join(tmpdir, 'intel.lic')
            write_file(os.environ['INTEL_LICENSE_FILE'], '# dummy license')

        elif app_class == PythonBundle or app_class == CargoPythonBundle:
            # $EBROOTPYTHON must be set for PythonBundle easyblock
            os.environ['EBROOTPYTHON'] = '/fake/install/prefix/Python/2.7.14-foss-2018a'

        elif app_class == GoPackage:
            # $EBROOTGO must be set for GoPackage easyblock
            os.environ['EBROOTGO'] = '/fake/install/prefix/Go/1.14'
            os.environ['EBVERSIONGO'] = '1.14'

        elif app_class in (JuliaPackage, JuliaBundle):
            # $EBROOTJULIA must be set for JuliaPackage/JuliaBundle easyblock
            os.environ['EBROOTJULIA'] = '/fake/install/prefix/Julia/1.6.7'
            os.environ['EBVERSIONJULIA'] = '1.6.7'

        # proper toolchain must be used for OpenFOAM(-Extend), to determine value to set for $WM_COMPILER;
        # non-system toolchain must be used for ELPA + FFTW*, because no toolchain options are set for system toolchain
        if app_class in (EB_ELPA, EB_FFTW, EB_FFTW_period_MPI, EB_OpenFOAM):
            write_file(os.path.join(tmpdir, 'GCC', '4.9.3-2.25'), '\n'.join([
                '#%Module',
                'setenv EBROOTGCC %s' % tmpdir,
                'setenv EBVERSIONGCC 4.9.3',
            ]))
            write_file(os.path.join(tmpdir, 'OpenMPI', '1.10.2-GCC-4.9.3-2.25'), '\n'.join([
                '#%Module',
                'setenv EBROOTOPENMPI %s' % tmpdir,
                'setenv EBVERSIONOPENMPI 1.10.2',
            ]))
            write_file(os.path.join(tmpdir, 'gompi', '2016a'), '\n'.join([
                '#%Module',
                'module load GCC/4.9.3-2.25',
                'module load OpenMPI/1.10.2-GCC-4.9.3-2.25',
            ]))
            os.environ['MODULEPATH'] = tmpdir
            toolchain = {'name': 'gompi', 'version': '2016a'}

        # extend easyconfig to make sure mandatory custom easyconfig paramters are defined
        extra_options = app_class.extra_options()
        for (key, val) in extra_options.items():
            if val[2] == MANDATORY:
                # use default value if any is set, otherwise use "foo"
                if val[0]:
                    test_param = val[0]
                else:
                    test_param = 'foo'
                extra_txt += '%s = "%s"\n' % (key, test_param)

        # test --module-only for GCC easyblock with withnvptx enabled,
        # like we do for recent GCC versions by default in easybuilders/easybuild-easyconfigs repo
        if app_class == EB_GCC:
            extra_txt += 'withnvptx = True\n'

        # write easyconfig file
        self.writeEC(ebname, name=name, version=version, extratxt=extra_txt, toolchain=toolchain)

        # take into account that for some easyblock, particular dependencies are hard required early on
        # (in prepare_step for example);
        # we just set the corresponding $EBROOT* environment variables here to fool it...
        req_deps = {
            # QScintilla easyblock requires that either PyQt or PyQt5 are available as dependency
            # (PyQt is easier, since PyQt5 is only supported for sufficiently recent QScintilla versions)
            'qscintilla.py': [('PyQt', '4.12')],
            # MotionCor2 and Gctf easyblock requires CUDA as dependency
            'motioncor2.py': [('CUDA', '10.1.105')],
            'gctf.py': [('CUDA', '10.1.105')],
        }
        easyblock_fn = os.path.basename(easyblock)
        for (dep_name, dep_version) in req_deps.get(easyblock_fn, []):
            dep_root_envvar = get_software_root_env_var_name(dep_name)
            os.environ[dep_root_envvar] = '/value/should/not/matter'
            dep_version_envvar = get_software_version_env_var_name(dep_name)
            os.environ[dep_version_envvar] = dep_version

        # initialize easyblock
        # if this doesn't fail, the test succeeds
        app = app_class(EasyConfig(self.eb_file))

        assert app.installdir.startswith(TMPDIR)  # Just to be sure...
        mkdir(app.installdir, parents=True)  # Pretend this exists

        # run all steps, most should be skipped
        orig_workdir = os.getcwd()
        try:
            with self.mocked_stdout_stderr():
                app.run_all_steps(run_test_cases=False)
        finally:
            change_dir(orig_workdir)

        if os.path.basename(easyblock) == 'modulerc.py':
            # .modulerc must be cleaned up to avoid causing trouble (e.g. "Duplicate version symbol" errors)
            modulerc = os.path.join(TMPDIR, 'modules', 'all', name, '.modulerc')
            if os.path.exists(modulerc):
                remove_file(modulerc)

            modulerc += '.lua'
            if os.path.exists(modulerc):
                remove_file(modulerc)
        else:
            modfile = os.path.join(TMPDIR, 'modules', 'all', name, version)
            if toolchain:
                modfile = '-'.join([modfile, toolchain['name'], toolchain['version']])
            luamodfile = '%s.lua' % modfile
            self.assertTrue(os.path.exists(modfile) or os.path.exists(luamodfile),
                            "Module file %s or %s was generated" % (modfile, luamodfile))

            if os.path.exists(modfile):
                modtxt = read_file(modfile)
            else:
                modtxt = read_file(luamodfile)

            none_regex = re.compile('None')
            self.assertFalse(none_regex.search(modtxt), "None not found in module file: %s" % modtxt)

        # cleanup
        app.close_log()
        remove_file(app.logfile)
        remove_dir(tmpdir)
    else:
        self.assertTrue(False, "Class found in easyblock %s" % easyblock)


def suite():
    """Return all easyblock --module-only tests."""
    def make_inner_test(easyblock, **kwargs):
        def innertest(self):
            template_module_only_test(self, easyblock, **kwargs)
        return innertest

    # initialize configuration (required for e.g. default modules_tool setting)
    cleanup()
    eb_go = eboptions.parse_options(args=['--prefix=%s' % TMPDIR])
    config.init(eb_go.options, eb_go.get_options_by_section('config'))
    build_options = {
        'external_modules_metadata': {},
        # enable --force --module-only
        'force': True,
        'module_only': True,
        'silent': True,
        'suffix_modules_path': GENERAL_CLASS,
        'valid_module_classes': config.module_classes(),
        'valid_stops': [x[0] for x in EasyBlock.get_steps()],
    }
    config.init_build_options(build_options=build_options)
    set_tmpdir()

    # dynamically generate a separate test for each of the available easyblocks
    easyblocks_path = get_paths_for("easyblocks")[0]
    all_pys = glob.glob('%s/*/*.py' % easyblocks_path)
    easyblocks = [eb for eb in all_pys if os.path.basename(eb) != '__init__.py' and '/test/' not in eb]

    # filter out no longer supported easyblocks, or easyblocks that are tested in a different way
    excluded_easyblocks = ['versionindependendpythonpackage.py']
    easyblocks = [e for e in easyblocks if os.path.basename(e) not in excluded_easyblocks]

    # add dummy PrgEnv-* modules, required for testing CrayToolchain easyblock
    for prgenv in ['PrgEnv-cray', 'PrgEnv-gnu', 'PrgEnv-intel', 'PrgEnv-pgi']:
        write_file(os.path.join(TMPDIR, 'modules', 'all', prgenv, '1.2.3'), "#%Module")

    # add empty module files for dependencies that are required for testing easyblocks
    for dep_mod_name in ('foo/1.2.3.4.5', 'PyTorch/1.12.1'):
        write_file(os.path.join(TMPDIR, 'modules', 'all', dep_mod_name), "#%Module")

    for easyblock in easyblocks:
        eb_fn = os.path.basename(easyblock)
        # dynamically define new inner functions that can be added as class methods to ModuleOnlyTest
        if eb_fn == 'systemcompiler.py':
            # use GCC as name when testing SystemCompiler easyblock
            innertest = make_inner_test(easyblock, name='GCC', version='system')
        elif eb_fn == 'systemmpi.py':
            # use OpenMPI as name when testing SystemMPI easyblock
            innertest = make_inner_test(easyblock, name='OpenMPI', version='system')
        elif eb_fn == 'craytoolchain.py':
            # make sure that a (known) PrgEnv is included as a dependency
            extra_txt = 'dependencies = [("PrgEnv-gnu/1.2.3", EXTERNAL_MODULE)]'
            innertest = make_inner_test(easyblock, name='CrayCC', extra_txt=extra_txt)
        elif eb_fn == 'modulerc.py':
            # exactly one dependency is included with ModuleRC generic easyblock (and name must match)
            extra_txt = 'dependencies = [("foo", "1.2.3.4.5")]'
            innertest = make_inner_test(easyblock, name='foo', version='1.2.3.4', extra_txt=extra_txt)
        elif eb_fn == 'intel_compilers.py':
            # custom easyblock for intel-compilers (oneAPI) requires v2021.x or newer
            innertest = make_inner_test(easyblock, name='intel-compilers', version='2021.1')
        elif eb_fn == 'openssl_wrapper.py':
            # easyblock to create OpenSSL wrapper expects an OpenSSL version
            innertest = make_inner_test(easyblock, name='OpenSSL-wrapper', version='1.1')
        elif eb_fn == 'torchvision.py':
            # torchvision easyblock requires that PyTorch is listed as dependency
            extra_txt = "dependencies = [('PyTorch', '1.12.1')]"
            innertest = make_inner_test(easyblock, name='torchvision', extra_txt=extra_txt)
        elif eb_fn == 'ucx_plugins.py':
            # install fake ucx_info command (used in make_module_extra)
            tmpdir = tempfile.mkdtemp()
            install_fake_command('ucx_info', FAKE_UCX_INFO, tmpdir)
            innertest = make_inner_test(easyblock, name='UCX-CUDA', tmpdir=tmpdir)
        else:
            # Make up some unique name
            innertest = make_inner_test(easyblock, name=eb_fn.replace('.', '-') + '-sw')

        innertest.__doc__ = "Test for using --module-only with easyblock %s" % easyblock
        innertest.__name__ = "test_easyblock_%s" % '_'.join(easyblock.replace('.py', '').split('/'))
        setattr(ModuleOnlyTest, innertest.__name__, innertest)

    return TestLoader().loadTestsFromTestCase(ModuleOnlyTest)


if __name__ == '__main__':
    res = TextTestRunner(verbosity=1).run(suite())
    remove_dir(TMPDIR)
    sys.exit(len(res.failures))
