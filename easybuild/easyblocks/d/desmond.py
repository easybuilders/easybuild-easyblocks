##
# Copyright 2009-2020 Ghent University
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
EasyBuild support for building and installing Desmond, implemented as an easyblock

@author: Samuel Moors, Vrije Universiteit Brussel (VUB)
"""
import os

from easybuild.easyblocks.generic.tarball import Tarball
from easybuild.tools.filetools import remove_dir
from easybuild.tools.run import run_cmd_qa


class EB_Desmond(Tarball):
    """Support for building/installing Desmond."""

    def install_step(self):
        """Custom install procedure for Desmond."""
        if os.path.exists(self.installdir):
            self.log.warning(
                "Found existing install directory %s, removing it to avoid problems",
                self.installdir,
            )
            remove_dir(self.installdir)

        qa = {
            '[Press ENTER to continue]': '',
        }
        std_qa = {
            r'SCHRODINGER directory:.*': self.installdir + '\ny',  # answer yes to create the directory
            r'    Your SCHRODINGER directory will be.*\n.*\nOK\?.*': 'y',
            r'Scratch directory\?.*': '/tmp',
            r'Are these choices correct\?.*': 'y',
            r'Create an application launcher for.*': 'n',
        }
        cmd = './INSTALL'
        run_cmd_qa(cmd, qa, std_qa=std_qa, log_all=True, simple=True, log_ok=True, maxhits=500)

    def sanity_check_step(self):
        """Custom sanity check for Desmond."""

        custom_paths = {
            'files': ['desmond', 'maestro', 'bioluminate', 'materials'],
            'dirs': [],
        }

        custom_commands = ['desmond -h']

        super(EB_Desmond, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_req_guess(self):
        """Custom guesses for path-like environment variables for Desmond."""
        guesses = super(EB_Desmond, self).make_module_req_guess()

        guesses['PATH'] = ['']

        return guesses

    def make_module_extra(self):
        """Set up SCHRODINGER environment variable"""
        txt = super(EB_Desmond, self).make_module_extra()
        txt += self.module_generator.set_environment('SCHRODINGER', self.installdir)
        return txt
