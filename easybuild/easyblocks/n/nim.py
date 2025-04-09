##
# Copyright 2018-2025 Ghent University
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
EasyBuild support for building and installing Nim, implemented as an easyblock

author: Kenneth Hoste (HPC-UGent)
"""
import os

from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.filetools import copy_file, move_file
from easybuild.tools.run import run_shell_cmd


class EB_Nim(EasyBlock):
    """Support for building/installing Nim."""

    def configure_step(self):
        """No configuration for Nim."""
        pass

    def build_step(self):
        """Custom build procedure for Nim."""

        # build Nim (bin/nim)
        run_shell_cmd("sh build.sh")

        # build koch management tool
        run_shell_cmd("bin/nim c -d:release koch")

        # rebuild Nim, with readline bindings
        run_shell_cmd("./koch boot -d:release -d:useLinenoise")

        # build nimble/nimgrep/nimsuggest tools
        run_shell_cmd("./koch tools")

    def install_step(self):
        """Custom install procedure for Nim."""

        run_shell_cmd("./koch geninstall")
        run_shell_cmd("sh install.sh %s" % self.installdir)

        # install.sh copies stuff into <prefix>/nim, so move it
        nim_dir = os.path.join(self.installdir, 'nim')
        for entry in os.listdir(nim_dir):
            move_file(os.path.join(nim_dir, entry), os.path.join(self.installdir, entry))

        # also copy nimble/nimgrep/nimsuggest tools
        for tool in ['nimble', 'nimgrep', 'nimsuggest']:
            copy_file(os.path.join('bin', tool), os.path.join(self.installdir, 'bin', tool))

    def sanity_check_step(self):
        """Custom sanity check for Nim."""
        custom_paths = {
            'files': ['bin/nim', 'bin/nimble', 'bin/nimgrep', 'bin/nimsuggest'],
            'dirs': ['config', 'doc', 'lib'],
        }
        super(EB_Nim, self).sanity_check_step(custom_paths=custom_paths)
