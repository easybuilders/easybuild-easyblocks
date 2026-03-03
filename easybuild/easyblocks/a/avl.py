##
# Copyright 2009-2018 Ghent University
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
EasyBuild support for installing AVL, implemented as an easyblock
Shamelessly ripped off from the ANSYS and MATLAB easyblocks.

@author: Kenneth Hoste (Ghent University)
@author: Bart Verleye (Centre for eResearch, Auckland)
@author: Chris Samuel (Swinburne University of Technology, Melbourne, Australia)
@author: Damian Alvarez (Forschungszentrum Juelich GmbH)
"""
import os

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.run import run_cmd
from easybuild.tools.filetools import write_file


class EB_AVL(PackedBinary):
    """Support for installing AVL."""

    def install_step(self):
        """Custom install procedure for AVL."""

        licserv = self.cfg['license_server']

        # try to find the license in a FlexLM license file/server
        if licserv is None:
            licserv = os.getenv('LM_LICENSE_FILE')

        if licserv is None:
            msg = "No viable license specifications found; "
            msg += "specify 'license_server' (port@example.server.com), or define $LM_LICENSE_FILE"
            raise EasyBuildError(msg)

        cmd = "./setup.sh --mode unattended --prefix %s" % self.installdir
        run_cmd(cmd, log_all=True, simple=True)

        # Get the first server if there are multiple servers
        licserv = licserv.split(':')[0]

        # Get the port and server
        licport, licserv = licserv.split('@')

        # create license file
        lictxt = '\n'.join([
            "SERVER %s 000000000000 %s" % (licserv, licport),
            "USE_SERVER",
        ])

        licfile = os.path.join(self.installdir, 'etc/lmx/license.dat')
        write_file(licfile, lictxt)

    def sanity_check_step(self):
        """Custom sanity check for AVL."""
        custom_paths = {
            'files': ['FIRE/bin/fire_launcher.py', 'bin/fire_wm', 'bin/diagnose'],
            'dirs': ["resource", "tools"]
        }
        super(EB_AVL, self).sanity_check_step(custom_paths=custom_paths)
