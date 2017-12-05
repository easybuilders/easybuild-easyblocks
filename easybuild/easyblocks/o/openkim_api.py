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
EasyBuild support for the Open Knowledgbase of Interatomic Models

See OpenKIM.org

@author: Jakob Schiotz (Tech. Univ. Denmark)
"""

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.run import run_cmd
import os

class EB_OpenKIM_minus_API(ConfigureMake):
    """Custom easyblock for OpenKIM-API"""

    def install_step(self):
        """
        Create the installation in correct location, and set version 1
        of the API as default (currently the only version available,
        but required nevertheless)
        
        - typical: 
            make install
            make install-set-default-to-v1
        """

        # Install as usual
        super(EB_OpenKIM_minus_API, self).install_step()

        # Set the default version
        cmd = "%s make install-set-default-to-v1 %s" % (self.cfg['preinstallopts'], self.cfg['installopts'])

        (out, _) = run_cmd(cmd, log_all=True, simple=False)

        return out
