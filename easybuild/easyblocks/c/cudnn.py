##
# Copyright 2012-2021 Ghent University
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
EasyBuild support for cuDNN, implemented as an easyblock

@author: Simon Branford (University of Birmingham)
@author: Robert Mijakovic (LuxProvide)
"""
from easybuild.easyblocks.generic.tarball import Tarball
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.systemtools import AARCH64, POWER, X86_64, get_cpu_architecture


class EB_cuDNN(Tarball):
    """Support for building cuDNN."""

    def __init__(self, *args, **kwargs):
        """ Init the cuDNN easyblock adding a new cudnnarch template var """
        myarch = get_cpu_architecture()
        if myarch == AARCH64:
            cudnnarch = 'aarch64sbsa'
        elif myarch == POWER:
            cudnnarch = 'ppc64le'
        elif myarch == X86_64:
            cudnnarch = 'x64'
        else:
            raise EasyBuildError("Architecture %s is not supported for cuDNN on EasyBuild", myarch)

        super(EB_cuDNN, self).__init__(*args, **kwargs)

        self.cfg['keepsymlinks'] = True
        self.cfg.template_values['cudnnarch'] = cudnnarch
        self.cfg.generate_template_values()
