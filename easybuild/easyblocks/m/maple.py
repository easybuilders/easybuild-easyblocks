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
EasyBuild support for installing Maple, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""
import glob
import os

from easybuild.easyblocks.generic.binary import Binary
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.run import run_cmd_qa


class EB_Maple(Binary):
    """Support for installing Maple."""

    def install_step(self):
        """Interactive install of Maple."""

        installers = glob.glob(os.path.join(self.builddir, 'Maple*Installer*'))
        if installers:
            if len(installers) == 1:
                cmd = installers[0]
            else:
                raise EasyBuildError("Found multiple installers: %s", ', '.join(installers))
        else:
            raise EasyBuildError("Could not locate installer in %s", self.builddir)

        qa = {
            'PRESS <ENTER> TO CONTINUE:': '',
            "Press [Enter] to continue:": '',
            'DO YOU ACCEPT THE TERMS OF THIS LICENSE AGREEMENT? (Y/N):': 'Y',
            "Do you accept this license? [y/n]:": 'y',
            'ENTER AN ABSOLUTE PATH, OR PRESS <ENTER> TO ACCEPT THE DEFAULT :': self.installdir,
            'IS THIS CORRECT? (Y/N):': 'Y',
            'Do you wish to have a shortcut installed on your desktop? ->1- Yes 2- No ENTER THE NUMBER ' +
            'FOR YOUR CHOICE, OR PRESS <ENTER> TO ACCEPT THE DEFAULT::': '2',
            "Do you wish to have a shortcut installed on your desktop? [Y/n]:": 'n',
            '->1- Single User License 2- Network License ENTER THE NUMBER FOR YOUR CHOICE, ' +
            'OR PRESS <ENTER> TO ACCEPT THE DEFAULT::': '2',
            'PRESS <ENTER> TO EXIT THE INSTALLER:': '',
            'License server (DEFAULT: ):': self.cfg['license_server'],
            "License server []:": self.cfg['license_server'],
            'Port number (optional) (DEFAULT: ):': '',
            '->1- Configure toolbox for Matlab 2- Do not configure at this time ENTER THE NUMBER FOR YOUR CHOICE, ' +
            'OR PRESS <ENTER> TO ACCEPT THE DEFAULT::': '2',
            "MATLAB Configuration [y/N]:": 'n',
            "Check for updates now [Y/n]:": 'n',
            "Use proxy server when checking for updates [y/N]:": 'n',
            "Downloads & Service Packs. [Y/n]:": 'n',
        }
        std_qa = {
            "Choose Install Folder \[.*\]:": self.installdir,
            "\[2\] Network License.*\nPlease choose an option \[.\] :": '2',
            "\[1\] Single Server.*\n.*\nPlease choose an option \[.\] :": '1',
            "Port number \[[0-9]+\]:": '',
            "Enable periodic checking for Maple .* updates after installation \[Y/n\]:": 'n',
        }

        no_qa = [
            'Graphical installers are not supported by the VM. The console mode will be used instead...',
            'Extracting the JRE from the installer archive...',
            'Launching installer...',
            "Configuring the installer for this system's environment...",
            'Unpacking the JRE...',
            '\[[-|]*',
        ]

        run_cmd_qa(cmd, qa, std_qa=std_qa, no_qa=no_qa, log_all=True, simple=True)

        upgrade_installers = glob.glob(os.path.join(self.builddir, 'Maple*Upgrade*'))
        if upgrade_installers:
            if len(upgrade_installers) == 1:
                cmd = upgrade_installers[0]
                qa = {
                    "Press [Enter] to continue:": '',
                    "Do you accept this license? [y/n]:": 'y',
                }
                std_qa = {
                    "Please specify the path to your existing Maple .* Installation.\s*\n\s*\[.*\]:": self.installdir,
                }
                run_cmd_qa(cmd, qa, std_qa=std_qa, log_all=True, simple=True)
            else:
                raise EasyBuildError("Found multiple upgrade installers: %s", ', '.join(upgrade_installers))
        else:
            self.log.info("No upgrade installers found in %s", self.builddir)

    def sanity_check_step(self):
        """Custom sanity check for Maple."""
        custom_paths = {
            'files': ['bin/maple', 'lib/maple.mla'],
            'dirs': [],
        }
        super(EB_Maple, self).sanity_check_step(custom_paths=custom_paths)
