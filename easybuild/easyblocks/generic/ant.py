##
# Copyright 2009-2013 Ghent University
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
EasyBuild support for software that uses the ant build tool
i.e. 'ant all' implemented as an easyblock
"""

import easybuild.tools.environment as env
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.filetools import run_cmd_qa


class Ant(EasyBlock):
    """
    Support for building and installing applications with ant install
    """
    def configure_step(self, cmd_prefix=''):
        """no op"""
        pass

    def build_step(self):
        """no op"""
        pass

    def install_step(self):
        """Custom build procedure for Maven."""
        env.setvar('M2_HOME', self.installdir)
        cmd = 'ant all'
        qa = {
            "[input] Do you want to continue? (yes, [no])": "yes"
        }
        no_qa = [
                r' *[java].*', 
                r' *[modello].*'
        ]

        run_cmd_qa(cmd, qa, no_qa=no_qa, log_all=True, simple=True)

