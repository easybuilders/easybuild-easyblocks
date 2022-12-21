##
# Copyright 2009-2022 Ghent University
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
"""
from distutils.version import LooseVersion
import os

from easybuild.easyblocks.generic.fortranpythonpackage import FortranPythonPackage
from easybuild.easyblocks.generic.pythonpackage import det_pylibdir
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import remove_dir
import easybuild.tools.toolchain as toolchain


class EB_scipy(FortranPythonPackage):
    """Support for installing the scipy Python package as part of a Python installation."""

    def __init__(self, *args, **kwargs):
        """Set scipy-specific test command."""
        super(EB_scipy, self).__init__(*args, **kwargs)

        self.testinstall = True
        self.testcmd = "cd .. && %(python)s -c 'import numpy; import scipy; scipy.test(verbose=2)'"

    def configure_step(self):
        """Custom configure step for scipy: set extra installation options when needed."""
        super(EB_scipy, self).configure_step()

        if LooseVersion(self.version) >= LooseVersion('0.13'):
            # in recent scipy versions, additional compilation is done in the install step,
            # which requires unsetting $LDFLAGS
            if self.toolchain.comp_family() in [toolchain.GCC, toolchain.CLANGGCC]:  # @UndefinedVariable
                self.cfg.update('preinstallopts', "unset LDFLAGS && ")

        # configure BLAS/LAPACK library to use with Meson for scipy >= 1.9.0
        if LooseVersion(self.version) >= LooseVersion('1.9.0'):
            lapack_lib = self.toolchain.lapack_family()
            if lapack_lib == toolchain.FLEXIBLAS:
                blas_lapack = 'flexiblas'
            elif lapack_lib == toolchain.INTELMKL:
                blas_lapack = 'mkl'
            elif lapack_lib == toolchain.OPENBLAS:
                blas_lapack = 'openblas'
            else:
                raise EasyBuildError("Unknown BLAS/LAPACK library used: %s", lapack_lib)

            meson_cmd = ' '.join([
                'meson',
                'setup',
                'build',
                '-Dblas=' + blas_lapack,
                '-Dlapack=' + blas_lapack,
            ])
            self.cfg.update('preinstallopts', meson_cmd + ' && ')

    def build_step(self):
        """
        Custom build step for scipy: don't run "python setup.py build" for scipy >= 1.9.0
        """
        if LooseVersion(self.version) < LooseVersion('1.9.0'):
            super(EB_scipy, self).build_step()

    def install_step(self):
        """
        Custom install step for scipy: clean up existing 'build' directory for scipy >= 1.9.0
        """
        if LooseVersion(self.version) >= LooseVersion('1.9.0'):
            # we need to clean up the build directory if it exists already,
            # to avoid that Meson detects that the build has been configured already
            # (when installing scipy for running the tests)
            build_dir = 'build'
            if os.path.exists(build_dir):
                remove_dir(build_dir)

        super(EB_scipy, self).install_step()

    def sanity_check_step(self, *args, **kwargs):
        """Custom sanity check for scipy."""

        # can't use self.pylibdir here, need to determine path on the fly using currently active 'python' command;
        # this is important for numpy installations for multiple Python version (via multi_deps)
        custom_paths = {
            'files': [],
            'dirs': [det_pylibdir()],
        }

        return super(EB_scipy, self).sanity_check_step(custom_paths=custom_paths)
