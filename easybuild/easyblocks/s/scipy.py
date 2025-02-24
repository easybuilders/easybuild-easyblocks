##
# Copyright 2009-2025 Ghent University
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
EasyBuild support for building and installing scipy, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Jasper Grimm (University of York)
@author: Sebastian Achilles (Juelich Supercomputing Centre)
"""
import os
import tempfile
from easybuild.tools import LooseVersion

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.fortranpythonpackage import FortranPythonPackage
from easybuild.easyblocks.generic.mesonninja import MesonNinja
from easybuild.easyblocks.generic.pythonpackage import PythonPackage, det_pylibdir
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.filetools import change_dir, copy_dir, copy_file


class EB_scipy(FortranPythonPackage, PythonPackage, MesonNinja):
    """Support for installing the scipy Python package as part of a Python installation."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Easyconfig parameters specific to scipy."""
        extra_vars = PythonPackage.extra_options(extra_vars=extra_vars)
        extra_vars = MesonNinja.extra_options(extra_vars=extra_vars)
        extra_vars.update({
            'enable_slow_tests': [False, "Run scipy test suite, including tests marked as slow", CUSTOM],
            'ignore_test_result': [None, "Run scipy test suite, but ignore test failures (True/False/None). Default "
                                         "(None) implies True for scipy < 1.9, and False for scipy >= 1.9", CUSTOM],
        })

        return extra_vars

    def __init__(self, *args, **kwargs):
        """Set scipy-specific test command."""
        # calling PythonPackage __init__ also lets MesonNinja work in an extension
        PythonPackage.__init__(self, *args, **kwargs)
        self.testinstall = True

        # use Meson/Ninja install procedure for scipy >= 1.9
        self.use_meson = LooseVersion(self.version) >= LooseVersion('1.9')

        # enforce scipy test suite results if not explicitly disabled for scipy >= 1.9
        if self.cfg['ignore_test_result'] is None:
            # automatically ignore scipy test suite results for scipy < 1.9, as we did in older easyconfigs
            self.cfg['ignore_test_result'] = LooseVersion(self.version) < '1.9'
            self.log.info("ignore_test_result not specified, so automatically set to %s for scipy %s",
                          self.cfg['ignore_test_result'], self.version)

        if self.cfg['ignore_test_result']:
            # used to maintain compatibility with easyconfigs predating scipy 1.9;
            # runs tests (serially) in a way that exits with code 0 regardless of test results,
            # see https://github.com/easybuilders/easybuild-easyblocks/issues/2237
            self.testcmd = "cd .. && %(python)s -c 'import numpy; import scipy; scipy.test(verbose=2)'"
        else:
            if LooseVersion(self.version) >= LooseVersion('1.11'):
                self.testcmd = " && ".join([
                    "cd ..",
                    # note: beware of adding --parallel here to speed up running the tests:
                    # in some contexts the test suite could hang because pytest-xdist doesn't deal well with cgroups
                    # cfr. https://github.com/pytest-dev/pytest-xdist/issues/658
                    "%(python)s %(srcdir)s/dev.py --no-build --install-prefix %(installdir)s test -v ",
                ])
            else:
                self.testcmd = " && ".join([
                    "cd ..",
                    "touch %(srcdir)s/.coveragerc",
                    "%(python)s %(srcdir)s/runtests.py -v --no-build --parallel %(parallel)s",
                ])

            if self.cfg['enable_slow_tests']:
                self.testcmd += " -m full "

    def configure_step(self):
        """Custom configure step for scipy: set extra installation options when needed."""

        # scipy >= 1.9.0 uses Meson/Ninja
        if self.use_meson:
            # configure BLAS/LAPACK library to use with Meson for scipy >= 1.9.0
            lapack_lib = self.toolchain.lapack_family()
            if lapack_lib == toolchain.FLEXIBLAS:
                blas_lapack = 'flexiblas'
            elif lapack_lib == toolchain.INTELMKL:
                blas_lapack = 'mkl-dynamic-lp64-seq'
            elif lapack_lib == toolchain.OPENBLAS:
                blas_lapack = 'openblas'
            else:
                raise EasyBuildError("Unknown BLAS/LAPACK library used: %s", lapack_lib)

            for opt in ('blas', 'lapack'):
                self.cfg.update('configopts', '-D%(opt)s=%(blas_lapack)s' % {'opt': opt, 'blas_lapack': blas_lapack})

            # need to have already installed extensions in PATH, PYTHONPATH for configure/build/install steps
            pythonpath = os.getenv('PYTHONPATH')
            pylibdir = det_pylibdir()
            env.setvar('PYTHONPATH', os.pathsep.join([os.path.join(self.installdir, pylibdir), pythonpath]))

            path = os.getenv('PATH')
            env.setvar('PATH', os.pathsep.join([os.path.join(self.installdir, 'bin'), path]))

            MesonNinja.configure_step(self)

        else:
            # scipy < 1.9.0 uses install procedure using setup.py
            FortranPythonPackage.configure_step(self)

        if LooseVersion(self.version) >= LooseVersion('0.13'):
            # in recent scipy versions, additional compilation is done in the install step,
            # which requires unsetting $LDFLAGS
            if self.toolchain.comp_family() in [toolchain.GCC, toolchain.CLANGGCC]:  # @UndefinedVariable
                self.cfg.update('preinstallopts', "unset LDFLAGS && ")

    def build_step(self):
        """Custom build step for scipy: use ninja for scipy >= 1.9.0"""
        if self.use_meson:
            MesonNinja.build_step(self)
        else:
            FortranPythonPackage.build_step(self)

    def test_step(self):
        """Run available scipy unit tests. Adapted from numpy easyblock"""

        if self.use_meson:
            # temporarily install scipy so we can run the test suite
            tmpdir = tempfile.mkdtemp()
            cwd = os.getcwd()

            tmp_builddir = os.path.join(tmpdir, 'build')
            tmp_installdir = os.path.join(tmpdir, 'install')

            # create a copy of the builddir
            copy_dir(cwd, tmp_builddir)
            change_dir(tmp_builddir)

            # reconfigure (to update prefix), and install to tmpdir
            orig_builddir = self.builddir
            orig_installdir = self.installdir
            self.builddir = tmp_builddir
            self.installdir = tmp_installdir
            MesonNinja.configure_step(self)
            MesonNinja.install_step(self)
            self.builddir = orig_builddir
            self.installdir = orig_installdir
            MesonNinja.configure_step(self)

            tmp_pylibdir = os.path.join(tmp_installdir, det_pylibdir())
            self.prepare_python()

            self.cfg['pretestopts'] = " && ".join([
                # LDFLAGS should not be set when testing numpy/scipy, because it overwrites whatever numpy/scipy sets
                # see http://projects.scipy.org/numpy/ticket/182
                "unset LDFLAGS",
                "export PYTHONPATH=%s:$PYTHONPATH" % tmp_pylibdir,
                "",
            ])
            self.cfg['runtest'] = self.testcmd % {
                'python': self.python_cmd,
                'srcdir': self.cfg['start_dir'],
                'installdir': tmp_installdir,
                'parallel': self.cfg.parallel,
            }

            MesonNinja.test_step(self)

        else:
            self.testcmd = self.testcmd % {
                'python': '%(python)s',
                'srcdir': self.cfg['start_dir'],
                'installdir': '',
                'parallel': self.cfg.parallel,
            }
            FortranPythonPackage.test_step(self)

    def install_step(self):
        """Custom install step for scipy: use ninja for scipy >= 1.9.0"""
        if self.use_meson:
            MesonNinja.install_step(self)

            # copy PKG-INFO file included in scipy source tarball to scipy-<version>.egg-info in installation,
            # so pip is aware of the scipy installation (required for 'pip list', 'pip check', etc.);
            # see also https://github.com/easybuilders/easybuild-easyblocks/issues/2901
            pkg_info = os.path.join(self.cfg['start_dir'], 'PKG-INFO')
            target_egg_info = os.path.join(self.installdir, self.pylibdir, 'scipy-%s.egg-info' % self.version)
            if os.path.isfile(pkg_info):
                copy_file(pkg_info, target_egg_info)
            else:
                cwd = os.getcwd()
                print_warning("%s not found in %s, so can't use it to create %s!", pkg_info, cwd, target_egg_info,
                              log=self.log)
        else:
            FortranPythonPackage.install_step(self)

    def sanity_check_step(self, *args, **kwargs):
        """Custom sanity check for scipy."""

        # can't use self.pylibdir here, need to determine path on the fly using currently active 'python' command;
        # this is important for numpy installations for multiple Python version (via multi_deps)
        custom_paths = {
            'files': [],
            'dirs': [det_pylibdir()],
        }

        # make sure that scipy is included in output of 'pip list',
        # so that 'pip check' passes if scipy is a required dependency for another Python package;
        # use case-insensitive match, since name is sometimes reported as 'SciPy'
        custom_commands = [r"pip list | grep -iE '^scipy\s+%s\s*$'" % self.version.replace('.', r'\.')]

        return PythonPackage.sanity_check_step(self, custom_paths=custom_paths, custom_commands=custom_commands)
