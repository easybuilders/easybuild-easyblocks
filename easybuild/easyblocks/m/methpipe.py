##
# Copyright 2013-2014 the Cyprus Institute
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
EasyBuild support for MethPipe

@author: Thekla Loizou (The Cyprus Institute)
"""
import os

from easybuild.easyblocks.generic.makecp import MakeCp
from easybuild.tools.filetools import run_cmd, mkdir

class EB_METHPIPE(MakeCp):
    """Support for building and installing MethPipe."""

    def configure_step(self):
        """Skip configure step"""
        pass

    def build_step(self, verbose=False):
        """Start the actual build"""
        paracmd = ''
        if self.cfg['parallel']:
            paracmd = "-j %s" % self.cfg['parallel']

        bindir = os.path.join(os.getcwd(), "bin")
   
        cmd = "%s make %s %s" % (self.cfg['premakeopts'], paracmd, self.cfg['makeopts'])
        (out, _) = run_cmd(cmd, log_all=True, simple=False, log_output=verbose)
      
        cmd = "%s make install %s" % (self.cfg['preinstallopts'], self.cfg['installopts'])
        (out, _) = run_cmd(cmd, log_all=True, simple=False, log_output=verbose)

	return out
