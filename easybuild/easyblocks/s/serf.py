##
# Copyright 2015 Fokko Masselink
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# the Hercules foundation (http://www.herculesstichting.be/in_English)
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
EasyBuild support for building and installing Serf, implemented as an easyblock

@author: Fokko Masselink
"""
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.run import run_cmd


class EB_serf(EasyBlock):
    """Support for building/installing serf."""

    def configure_step(self):
        """
        Configure build 
        """
        pass

    def build_step(self):
        """
        Build serf using 'scons PREFIX=self.installdir'
        """
        cmd = "scons APR=$EBROOTAPR APU=$EBROOTAPRMINUTIL PREFIX=%s" % (self.installdir)
        run_cmd(cmd, log_all=True, simple=True)

    def install_step(self):
        """
        Install serf using 'scons install'
        """
        cmd = "scons install"
        run_cmd(cmd, log_all=True, simple=True)

    def sanity_check_step(self):
        """Custom sanity check for Serf."""

        libs = ["libserf-1.a", "libserf-1.so"]

        custom_paths = {
            'files':["lib/%s" % x for x in libs],
            'dirs':[],
        }
        super(EB_serf, self).sanity_check_step(custom_paths=custom_paths)

