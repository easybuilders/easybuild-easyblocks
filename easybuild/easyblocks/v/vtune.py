# #
# Copyright 2013-2024 Ghent University
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

from easybuild.easyblocks.generic.intelbase import IntelBase, ACTIVATION_NAME_2012, LICENSE_FILE_NAME_2012


class EB_VTune(IntelBase):
    """
    Support for installing Intel VTune
    """

    def __init__(self, *args, **kwargs):
        """Easyblock constructor; define class variables."""
        super(EB_VTune, self).__init__(*args, **kwargs)

        # recent versions of VTune are installed to a subdirectory
        self.subdir = ''
        loosever = LooseVersion(self.version)
        if loosever >= LooseVersion('2021'):
            self.subdir = os.path.join('vtune', self.version)
        elif loosever >= LooseVersion('2020'):
            self.subdir = 'vtune_profiler'
        elif loosever >= LooseVersion('2018'):
            self.subdir = 'vtune_amplifier'
        elif loosever >= LooseVersion('2013_update12'):
            self.subdir = 'vtune_amplifier_xe'

    def prepare_step(self, *args, **kwargs):
        """Since 2019u3 there is no license required."""
        if LooseVersion(self.version) >= LooseVersion('2019_update3'):
            kwargs['requires_runtime_license'] = False
        super(EB_VTune, self).prepare_step(*args, **kwargs)

    def make_installdir(self):
        """Do not create installation directory, install script handles that already."""
        super(EB_VTune, self).make_installdir(dontcreate=True)

    def install_step(self):
        """
        Actual installation
        - create silent cfg file
        - execute command
        """
        silent_cfg_names_map = None

        if LooseVersion(self.version) <= LooseVersion('2013_update11'):
            silent_cfg_names_map = {
                'activation_name': ACTIVATION_NAME_2012,
                'license_file_name': LICENSE_FILE_NAME_2012,
            }

        super(EB_VTune, self).install_step(silent_cfg_names_map=silent_cfg_names_map)

    def make_module_req_guess(self):
        """Find reasonable paths for VTune"""
        return self.get_guesses_tools()

    def sanity_check_step(self):
        """Custom sanity check paths for VTune."""
        if LooseVersion(self.version) >= LooseVersion('2020'):
            binaries = ['amplxe-feedback', 'amplxe-runss', 'vtune', 'vtune-gui']
        else:
            binaries = ['amplxe-cl', 'amplxe-feedback', 'amplxe-gui', 'amplxe-runss']

        custom_paths = self.get_custom_paths_tools(binaries)

        custom_commands = []
        if LooseVersion(self.version) >= LooseVersion('2020'):
            custom_commands.append('vtune --version')
        else:
            custom_commands.append('amplxe-cl --version')

        super(EB_VTune, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
