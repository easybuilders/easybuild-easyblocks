##
# Copyright 2009-2023 Ghent University
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
"""
import os
from distutils.version import LooseVersion

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.fortranpythonpackage import FortranPythonPackage
from easybuild.easyblocks.generic.mesonninja import MesonNinja
from easybuild.easyblocks.generic.pythonpackage import det_pylibdir
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd


class EB_scipy(FortranPythonPackage, MesonNinja):
    """Support for installing the scipy Python package as part of a Python installation."""

    def __init__(self, *args, **kwargs):
        """Set scipy-specific test command."""
        super(EB_scipy, self).__init__(*args, **kwargs)

        self.use_meson = LooseVersion(self.version) >= LooseVersion('1.9')
        self.pylibdir = None
        self.testinstall = True
        self.testcmd = "cd .. && %(python)s -c 'import numpy; import scipy; scipy.test(verbose=2)'"

    def configure_step(self):
        """Custom configure step for scipy: set extra installation options when needed."""
        self.pylibdir = det_pylibdir()
        
        # scipy >= 1.9.0 uses Meson/Ninja
        if self.use_meson:
            # configure BLAS/LAPACK library to use with Meson for scipy >= 1.9.0
            lapack_lib = self.toolchain.lapack_family()
            if lapack_lib == toolchain.FLEXIBLAS:
                blas_lapack = 'flexiblas'
            elif lapack_lib == toolchain.INTELMKL:
                blas_lapack = 'mkl'
            elif lapack_lib == toolchain.OPENBLAS:
                blas_lapack = 'openblas'
            else:
                raise EasyBuildError("Unknown BLAS/LAPACK library used: %s", lapack_lib) 
            
            configopts = '-Dblas=%(blas_lapack)s -Dlapack=%(blas_lapack)s' % {'blas_lapack': blas_lapack}
            self.cfg.update('configopts', configopts)
            
            pythonpath = os.getenv('PYTHONPATH')
            env.setvar('PYTHONPATH', os.pathsep.join([os.path.join(self.installdir, self.pylibdir), pythonpath]))
            
            path = os.getenv('PATH')
            env.setvar('PATH', os.pathsep.join([os.path.join(self.installdir, 'bin'), path]))

            MesonNinja.configure_step(self)
        else:
            super(EB_scipy, self).configure_step()

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
            super(EB_scipy, self).build_step()

    def test_step(self):
        """Custom test step for scipy: skip if scipy >= 1.9.0"""
        if self.use_meson:
            # need to run `ninja install` before we can run the test
            pass
        else:
            super(EB_scipy, self).build_step()

    def install_step(self):
        """Custom install step for scipy: use ninja for scipy >= 1.9.0"""
        if self.use_meson:
            self.cfg['installopts'] = ""
            MesonNinja.install_step(self)
           
           # also run the test
            python_root = get_software_root('Python')
            python_bin = os.path.join(python_root, 'bin', 'python')
            run_cmd(self.testcmd % {'python': python_bin}, log_all=True, simple=True)
        else:
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
