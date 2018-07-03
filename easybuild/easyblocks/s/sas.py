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
EasyBuild support for building and installing SAS, implemented as an easyblock
"""
import os

from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.run import run_cmd_qa


class EB_SAS(EasyBlock):
    """Support for building/installing SAS."""

    def configure_step(self):
        """No custom configurationprocedure for SAS."""
        pass

    def build_step(self):
        """No custom build procedure for SAS."""
        pass

    def install_step(self):
        """Custom install procedure for SAS."""
        qa = {
            "SAS Home:": self.installdir,
            "Install SAS Software (default: Yes):": '',
            "Configure SAS Software (default: Yes):": '',
            "SAS Installation Data File:": '',
            "Press Enter to continue:": '',
            "Configure as a Unicode server (default: No):": 'N',
            "SAS/ACCESS Interface to MySQL (default: Yes):": 'N',
            "SAS/ACCESS Interface to Oracle (default: Yes):": 'N',
            "SAS/ACCESS Interface to Sybase (default: Yes):": 'N',
            "SAS/ACCESS Interface to SAP ASE (default: Yes):": 'N',
            "Use PAM Authentication (default: No):": 'N',
            "Port Number:": '',
            "Configure SAS Studio Basic (default: Yes):": 'N',
            "Press Enter to finish:": '',
        }
        std_qa = {
            "Incomplete Deployment\s*(.*[^:])+Selection:": '2',  # 2: Ignore previous deployment and start again
            "Select a language(.*[^:]\s*\n)+Selection:": '',
            "Select Deployment Task\s*(.*[^:]\s*\n)+Selection:": '',
            "Specify SAS Home\s*(.*[^:]\s*\n)+Selection:": '2',  # Create a new SAS Home
            "Select Deployment Type\s*(.*[^:]\n)+Selection:": '2',  # 2: Install SAS Foundation
            "Select Products to Install\s*(.*[^:]\n)+Selection:": '1',  # SAS Foundation
            "Product\s*(.*[^:]\n)+Selections:": '',
            "Select Language Support\s*(.*[^:]\n)+Selections:": '',
            "Select Regional Settings\s*(.*[^:]\n)+Selection:": '',
            "Select Support Option\s*(.*[^:]\n)+Selection:": '2',  # 2: Do Not Send
        }
        no_qa = [
            "\.\.\.$",
        ]
        run_cmd_qa("./setup.sh -console", qa, no_qa=no_qa, std_qa=std_qa, log_all=True, simple=True)

    def sanity_check_step(self):
        """Custom sanity check for SAS."""
        custom_paths = {
            'files': [os.path.join('SASFoundation', self.version, 'sas')],
            'dirs': ['licenses', os.path.join('SASFoundation', self.version, 'bin')],
        }
        super(EB_SAS, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_req_guess(self):
        """Custom path locations for SAS."""
        return {
            'PATH': [os.path.join('SASFoundation', self.version)],
        }
