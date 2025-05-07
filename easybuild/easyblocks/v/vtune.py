# #
# Copyright 2013-2025 Ghent University
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
EasyBuild support for installing Intel VTune, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
@author: Damian Alvarez (Forschungzentrum Juelich GmbH)
"""
from easybuild.tools import LooseVersion
import os

from easybuild.easyblocks.generic.intelbase import IntelBase
from easybuild.tools.build_log import EasyBuildError


class EB_VTune(IntelBase):
    """
    Support for installing Intel VTune
    - minimum version suported: 2020.x
    """

    def __init__(self, *args, **kwargs):
        """Easyblock constructor; define class variables."""
        super(EB_VTune, self).__init__(*args, **kwargs)

        # recent versions of VTune are installed to a subdirectory
        self.subdir = ''
        loosever = LooseVersion(self.version)
        if loosever < LooseVersion('2020'):
            raise EasyBuildError(
                f"Version {self.version} of {self.name} is unsupported. Mininum supported version is 2020.0."
            )

        if loosever >= LooseVersion('2024'):
            self.subdir = os.path.join('vtune', '.'.join([str(loosever.version[0]), str(loosever.version[1])]))
        elif loosever >= LooseVersion('2021'):
            self.subdir = os.path.join('vtune', self.version)
        elif loosever >= LooseVersion('2020'):
            self.subdir = 'vtune_profiler'

        # prepare module load environment
        self.prepare_intel_tools_env()

    def prepare_step(self, *args, **kwargs):
        """Since 2019u3 there is no license required."""
        kwargs['requires_runtime_license'] = False
        super(EB_VTune, self).prepare_step(*args, **kwargs)

    def make_installdir(self):
        """Do not create installation directory, install script handles that already."""
        super(EB_VTune, self).make_installdir(dontcreate=True)

    def sanity_check_step(self):
        """Custom sanity check paths for VTune."""
        binaries = ['amplxe-feedback', 'amplxe-runss', 'vtune', 'vtune-gui']
        custom_paths = self.get_custom_paths_tools(binaries)
        custom_commands = ['vtune --version']

        super(EB_VTune, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
