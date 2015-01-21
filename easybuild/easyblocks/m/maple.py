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
EasyBuild support for installing Maple, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""

import os
import shutil

from easybuild.easyblocks.generic.binary import Binary
from easybuild.tools.run import run_cmd_qa


class EB_Maple(Binary):
    """Support for installing Maple."""

    def install_step(self):
        """Interactive install of Maple."""

        cmd = os.path.join(self.builddir, self.src[0]['name'])

        license_option = None
        if self.cfg['license_server'] is not None:
            # Network License
            license_option = '2'
        else:
            self.log.error("A license server should be specified.")

        choose_number = "ENTER THE NUMBER FOR YOUR CHOICE, OR PRESS <ENTER> TO ACCEPT THE DEFAULT::"
        qa = {
            "PRESS <ENTER> TO CONTINUE:": '',  # Maple 15, 17
            "Press [Enter] to continue:": '',  # Maple 18
            "DO YOU ACCEPT THE TERMS OF THIS LICENSE AGREEMENT? (Y/N):": 'Y',  # Maple 15, 17
            "Do you accept this license? [y/n]:": 'y',  # Maple 18
            "ENTER AN ABSOLUTE PATH, OR PRESS <ENTER> TO ACCEPT THE DEFAULT :": self.installdir,  # Maple 15, 17
            "IS THIS CORRECT? (Y/N):": 'Y',
            "Do you wish to have a shortcut installed on your desktop? ->1- Yes 2- No " + choose_number: '2',  # Maple 15, 17
            "->1- Single User License 2- Network License " + choose_number: license_option,
            "PRESS <ENTER> TO EXIT THE INSTALLER:": '',
            "Port number (optional) (DEFAULT: ):": '',
            "->1- Configure toolbox for Matlab 2- Do not configure at this time " + choose_number: '2',  # Maple 15
            "->1- Configure toolbox for MATLAB 2- Do not configure at this time " + choose_number: '2',  # Maple 17
            "MATLAB Configuration [y/N]:": 'n',  # Maple 18
            "Enable periodic checking for Maple 18 updates after installation [Y/n]:": 'n',  # Maple 18
            "Check for updates now [Y/n]:": 'n',  # Maple 18
            "Use proxy server when checking for updates [y/N]:": 'n',  # Maple 18
            "Downloads & Service Packs. [Y/n]: ": 'n',  # Maple 18
        }

        license_server_port = self.cfg['license_server_port']
        if license_server_port is None:
            license_server_port = ''

        stdqa = {
            "Choose Install Folder .*:": self.installdir,  # Maple 18
            "Do you wish to have a shortcut installed on your desktop\?.*[Y/n]:": 'n',  # Maple 18
            "[1] Single User License: .*[2] Network License: .*Please choose an option [1] :": license_option,  # Maple 18
            "[1] Single Server: .*[2] Redundant Server: .*Please choose an option [1] :": '1',  # Maple 18
            "License server .*:": self.cfg['license_server'],  # Maple 15, 17, 18
            "Port number [.*]:": license_server_port,
        }

        no_qa = [
            "Graphical installers are not supported by the VM. The console mode will be used instead...",
            "Extracting the JRE from the installer archive...",
            "Launching installer...",
            "Configuring the installer for this system's environment...",
            "Unpacking the JRE...",
            '\[[-|]*',
            '\s*#+\s*',
        ]

        run_cmd_qa(cmd, qa, no_qa=no_qa, std_qa=stdqa, log_all=True, simple=True)

    def sanity_check_step(self):
        """Custom sanity check for Maple."""
        custom_paths =  {
            'files': ['bin/maple', 'bin/xmaple', 'lib/maple.mla'],
            'dirs': [],
        }
        super(EB_Maple, self).sanity_check_step(custom_paths=custom_paths)
