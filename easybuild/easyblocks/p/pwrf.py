##
# Copyright 2009-2018 Ghent University
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
EasyBuild support for building and installing Polar WRF (PWRF), 
implemented as an easyblock that wraps arount the WRF block.


@author: Oliver Stueker (ACENET/Compute Canada)
"""
import os
import re
import sys

from distutils.version import LooseVersion

from easybuild.easyblocks.wrf import EB_WRF
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import move_file, symlink 

class EB_PWRF(EB_WRF):
    """Support for building/installing Polar WRF (PWRF)."""
    
    def configure_step(self):
        """Configure PWRF build:
        - replace certain WRF files by those provided by PWRF
        - call EB_WRF.configure_step()
        """
        wrf_files_to_update = [
            'share/module_soil_pre.F',
            'run/LANDUSE.TBL',
            'run/VEGPARM.TBL',
            'dyn_em/module_first_rk_step_part1.F',
            'dyn_em/module_big_step_utilities_em.F',
            'dyn_em/module_initialize_real.F',
            'phys/module_sf_noahlsm.F',
            'phys/module_sf_noahdrv.F',
            'phys/module_surface_driver.F',
            'phys/module_sf_noahlsm_glacial_only.F',
            'phys/module_sf_noah_seaice.F',
            'phys/module_sf_noah_seaice_drv.F',
            'phys/module_mp_morr_two_moment.F',
        ]

        for wrf_file in wrf_files_to_update:
            pwrf_file = '../PWRF'+self.version+'/'+ wrf_file + '.PWRF' + self.version

            move_file( wrf_file,  wrf_file + '-unpolar')
            symlink( pwrf_file, wrf_file )

        super(EB_PWRF, self).configure_step()

