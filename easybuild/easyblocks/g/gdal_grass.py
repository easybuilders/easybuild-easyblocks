##
# Copyright 2009-2017 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
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
EasyBuild support for building and installing GDAL-GRASS, implemented as an easyblock

@author: Benjamin Roberts (Landcare Research New Zealand Ltd)
"""
import os

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.systemtools import get_shared_lib_ext

class EB_GDAL_minus_GRASS(ConfigureMake):
    """Support for building/installing the GDAL-GRASS plugin."""

    # Only the sanity check should need to be different
    def sanity_check_step(self):
        """
        Custom sanity check for GDAL-GRASS
        """
        if os.getenv('EBROOTGDAL') is None:
            raise EasyBuildError("$EBROOTGDAL is not defined for some reason -- check environment")
        else:
            gdalplugindir = os.path.join(os.getenv('EBROOTGDAL'), 'lib', 'gdalplugins')
            for libbase in ['gdal_GRASS', 'ogr_GRASS']:
                libname = "%s.%s" % (libbase, get_shared_lib_ext())
                fulllibpath = os.path.join(gdalplugindir, libname)
                if not os.path.isfile(fulllibpath):
                    return False

        return True
