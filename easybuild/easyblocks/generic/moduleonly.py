##
# Copyright 2018-2019 Ghent University
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
EasyBuild support for installing a software-specific .modulerc file

@author: Kenneth Hoste (Ghent University)
@author: Maxime Boissonneault (Compute Canada)
"""
from easybuild.framework.easyblock import EasyBlock


class ModuleOnly(EasyBlock):
    """
    Generic easyblock to create a module-only installation
    """

    def configure_step(self):
        """Do nothing."""
        pass

    def build_step(self):
        """Do nothing."""
        pass

    def install_step(self):
        """Do nothing."""
        pass

    def post_install_step(self, *args, **kwargs):
        """Do nothing."""
        pass

    def cleanup_step(self):
        """Do nothing."""
        pass

    def permissions_step(self):
        """Do nothing."""
        pass

    def sanity_check_step(self, *args, **kwargs):
        """
        Nothing is being installed, so just being able to load the (fake) module is sufficient
        """
        self.log.info("Testing loading of module '%s' by means of sanity check" % self.full_mod_name)
        fake_mod_data = self.load_fake_module(purge=True)
        self.log.debug("Cleaning up after testing loading of module")
        self.clean_up_fake_module(fake_mod_data)
