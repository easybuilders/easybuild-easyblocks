# #
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
# #
"""
EasyBuild support for installing only the FFTW interfaces for the Intel Math Kernel Library (MKL),
implemented as an easyblock

@author: Bart Oldeman (McGill University, Calcul Quebec, Compute Canada)
"""
import os

from easybuild.easyblocks.imkl import EB_imkl
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root


class EB_imkl_minus_FFTW(EB_imkl):
    """
    Class that can be used to install mkl FFTW interfaces only
    """

    def prepare_step(self, *args, **kwargs):
        """Custom prepare step: make sure imkl is available as dependency."""
        super(EB_imkl_minus_FFTW, self).prepare_step(*args, **kwargs)

        imkl_root = get_software_root('imkl')
        if not imkl_root:
            raise EasyBuildError("Required imkl dependency is missing!")

    def install_step(self):
        """Install Intel MKL FFTW interfaces"""
        # correct mkl_basedir, since build of FFTW interfaces needs to be done from imkl install directory
        self.mkl_basedir = os.getenv('MKLROOT')
        self.build_mkl_fftw_interfaces(os.path.join(self.installdir, 'lib'))

    def make_module_step(self, *args, **kwargs):
        """
        Custom paths of imkl are unnecessary as imkl-FFTW only ships libraries under the 'lib' subdir
        Use generic make_module_step skipping imkl
        """
        return super(EB_imkl, self).make_module_step(*args, **kwargs)

    def make_module_extra(self):
        """Custom extra variables to set in module file"""
        # bypass extra module variables for imkl
        return super(EB_imkl, self).make_module_extra()

    def post_processing_step(self):
        """Custom post install step for imkl-FFTW"""
        # bypass post_processing_step of imkl easyblock
        pass

    def sanity_check_step(self):
        """Custom sanity check for imkl-FFTW: check if all libraries for FFTW interfaces are there."""
        custom_paths = {
            'files': [os.path.join(self.installdir, 'lib', x) for x in self.get_mkl_fftw_interface_libs()],
            'dirs': [],
        }
        super(EB_imkl, self).sanity_check_step(custom_paths=custom_paths)
