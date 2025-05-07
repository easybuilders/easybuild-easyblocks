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
EasyBuild support for installing only the MPI interfaces for FFTW,
implemented as an easyblock

@author: Bart Oldeman (McGill University, Calcul Quebec, Digital Research Alliance of Canada)
"""
import os
import glob

from easybuild.easyblocks.fftw import EB_FFTW
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root
from easybuild.tools.filetools import remove


class EB_FFTW_period_MPI(EB_FFTW):
    """Support for building/installing FFTW.MPI"""

    @staticmethod
    def extra_options():
        """Modify defaults for custom easyconfig parameters for FFTW."""

        extra_vars = EB_FFTW.extra_options()
        # change defaults for unneeded or impossible options for MPI libraries
        extra_vars['with_openmp'][0] = False
        extra_vars['with_threads'][0] = False
        extra_vars['with_quad_prec'][0] = False
        return extra_vars

    def prepare_step(self, *args, **kwargs):
        """Custom prepare step: make sure FFTW is available as dependency."""
        super(EB_FFTW_period_MPI, self).prepare_step(*args, **kwargs)

        fftw_root = get_software_root('FFTW')
        if not fftw_root:
            raise EasyBuildError("Required FFTW dependency is missing!")

    def post_processing_step(self):
        """Custom post install step for FFTW.MPI"""

        # remove everything except include files that are already in non-MPI FFTW dependency.
        remove(glob.glob(os.path.join(self.installdir, 'lib*', 'libfftw.*')) +
               glob.glob(os.path.join(self.installdir, 'lib*', 'libfftw[lf].*')) +
               glob.glob(os.path.join(self.installdir, 'lib*/pkgconfig')) +
               glob.glob(os.path.join(self.installdir, 'lib*/cmake')) +
               [os.path.join(self.installdir, p) for p in ['bin', 'share']])
        super(EB_FFTW_period_MPI, self).post_processing_step()

    def sanity_check_step(self):
        """Custom sanity check for FFTW.MPI: check if all libraries/headers for MPI interfaces are there."""
        super(EB_FFTW_period_MPI, self).sanity_check_step(mpionly=True)
