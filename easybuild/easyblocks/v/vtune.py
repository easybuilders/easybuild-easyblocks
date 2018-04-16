# #
# Copyright 2013 Ghent University
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
from distutils.version import LooseVersion

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
        if loosever >= LooseVersion('2013_update12') and loosever < LooseVersion('2018'):
            self.subdir = 'vtune_amplifier_xe'
        elif loosever >= LooseVersion('2018'):
            self.subdir = 'vtune_amplifier'

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
        binaries = ['amplxe-cl', 'amplxe-feedback', 'amplxe-gui', 'amplxe-runss']
        custom_paths = self.get_custom_paths_tools(binaries)
        super(EB_VTune, self).sanity_check_step(custom_paths=custom_paths)
