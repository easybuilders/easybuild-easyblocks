##
# Copyright 2014 Ghent University
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
# along with EasyBuild. If not, see <http://www.gnu.org/licenses/>.
##
"""
@author: Maxime Boissonneault (Calcul Quebec, Compute Canada)
"""
import os
import re

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.run import run_cmd_qa
from easybuild.tools.run import run_cmd


class EB_OasysLSDyna(PackedBinary):
    """Support for installing OasysLSDyna"""
    @staticmethod
    def extra_options(extra_vars=None):
        """
        Define list of files or directories to be copied after make
        """
        extra_vars = PackedBinary.extra_options(extra_vars=extra_vars)
        return extra_vars

    def install_step(self):
        """Build by running the command with the inputfiles"""
        run_cmd("cd %s/install* && pwd" % self.builddir, log_all=True)
        cmd = "cd %s/install* && pwd && ./setup.csh" % self.builddir
        qanda = {
            "Select FULL/UPDATE or QUIT(to exit installation) ...": 'FULL',
            "Do you want to change the installation directory? (Y/N/Quit)": 'Y',
            "Enter the FULL PATH of the directory into which you want to put the software.  ? :": self.installdir,
            "Are you sure you want to install in this directory? [Y/N]": 'Y',
            'Do you want to set up the Oasys Ltd. LS-DYNA Environment flexlm server? [Y/N]': 'N',
            'Do you want to set up an OA_ADMIN directory? [Y/N]': 'N'
        }
        run_cmd_qa(cmd, qanda, log_all=True)

    def sanity_check_step(self):
        """Custom sanity check for Oasys LS Dyna."""

        custom_paths = {
                        'files':['oasys'],
                        'dirs':['lib64']
                       }

        super(EB_OasysLSDyna, self).sanity_check_step(custom_paths=custom_paths)
