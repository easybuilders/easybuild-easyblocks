##
# Copyright 2019-2019 Bart Oldeman, McGill University, Compute Canada
#
# This file is triple-licensed under GPLv2 (see below), MIT, and
# BSD three-clause licenses.
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
EasyBuild support for installing the Intel compiler suite, implemented as an easyblock

@author: Bart Oldeman (McGill University, Compute Canada)
"""

from easybuild.easyblocks.icc import EB_icc
from easybuild.easyblocks.ifort import EB_ifort


class EB_iccifort(EB_ifort, EB_icc):
    """
    Class that can be used to install iccifort
    """

    def sanity_check_step(self):
        """Custom sanity check paths for iccifort."""
        EB_icc.sanity_check_step(self)
        EB_ifort.sanity_check_step(self)

    def make_module_extra(self):
        txt = super(EB_iccifort, self).make_module_extra()

        # also define $EBROOT* and $EBVERSION* for icc/ifort
        txt += self.module_generator.set_environment('EBROOTICC', self.installdir)
        txt += self.module_generator.set_environment('EBROOTIFORT', self.installdir)
        txt += self.module_generator.set_environment('EBVERSIONICC', self.version)
        txt += self.module_generator.set_environment('EBVERSIONIFORT', self.version)

        return txt
