##
# Copyright 2009-2020 Ghent University
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
EasyBuild support for installing Mesa, implemented as an easyblock

@author: Andrew Edmondson (University of Birmingham)
"""

from easybuild.easyblocks.generic.mesonninja import MesonNinja
from easybuild.tools.systemtools import POWER, X86_64, get_cpu_architecture, get_cpu_features


class EB_Mesa(MesonNinja):
    def configure_step(self, cmd_prefix=''):
        """
        Customise the configopts based on the platform
        """
        arch = get_cpu_architecture()
        if arch == X86_64:
            self.cfg.update('configopts', "-Dgallium-drivers='swrast,swr'")
        elif arch == POWER:
            self.cfg.update('configopts', "-Dgallium-drivers='swrast'")

        features = set(get_cpu_features())
        arches = []
        if arch == X86_64:
            if 'avx' in features or 'avx1.0' in features:
                arches.append('avx')
            if 'avx2' in features:
                arches.append('avx2')
            if 'avx512f' in features:
                # AVX-512 Foundation - introduced in Skylake
                arches.append('skx')
            if 'avx512er' in features:
                # AVX-512 Exponential and Reciprocal Instructions implemented in Knights Landing
                arches.append('knl')
            if arches:
                self.cfg.update('configopts', "-Dswr-arches=%s" % ','.join(arches))

        return super(EB_Mesa, self).configure_step(cmd_prefix=cmd_prefix)
