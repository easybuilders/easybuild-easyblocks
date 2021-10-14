# #
# Copyright 2009-2021 Ghent University
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

from easybuild.easyblocks.i.imkl import EB_imkl
from easybuild.tools.filetools import mkdir


class EB_imkl_minus_FFTW(EB_imkl):
    """
    Class that can be used to install mkl FFTW interfaces only
    """

    def install_step(self):
        """Don't install imkl itself"""
        pass

    def make_module_req_guess(self):
        """Bypass imkl paths, only use standard lib location"""
        return super(EB_imkl, self).make_module_req_guess()

    def make_module_extra(self):
        """Bypass extra module variables from imkl"""
        return super(EB_imkl, self).make_module_extra()

    def post_install_step(self):
        """Install FFTW interfaces"""
        super(EB_imkl, self).post_install_step()
        self.mkl_basedir = os.getenv('MKLROOT')
        libdir = os.path.join(self.installdir, 'lib')
        mkdir(libdir)
        self.build_interfaces(libdir)

    def sanity_check_step(self):
        """Check if all archives are there"""
        custom_paths = {
            'files': [os.path.join(self.installdir, 'lib', lib) for lib in self.get_interface_libs()],
            'dirs': [os.path.join(self.installdir, 'lib')],
        }
        super(EB_imkl, self).sanity_check_step(custom_paths=custom_paths)
