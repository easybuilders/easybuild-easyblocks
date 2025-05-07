##
# Copyright 2023-2025 Ghent University
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
EasyBuild support for building and installing PALM, implemented as an easyblock

@author: Viktor Rehnberg (Chalmers University of Technology)
"""
import os

from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.filetools import find_glob_pattern
from easybuild.tools.run import run_shell_cmd


class EB_PALM(EasyBlock):
    """Support for building/installing PALM."""

    def __init__(self, *args, **kwargs):
        """Initialise PALM easyblock."""
        super(EB_PALM, self).__init__(*args, **kwargs)

    def configure_step(self):
        """No configuration procedure for PALM."""
        pass

    def build_step(self):
        """No build procedure for PALM."""
        pass

    def install_step(self):
        """Custom install procedure for PALM."""

        install_script_pattern = "install"
        if self.dry_run:
            install_script = install_script_pattern
        else:
            install_script = find_glob_pattern(install_script_pattern)

        cmd = ' '.join([
            self.cfg['preinstallopts'],
            "bash",
            install_script,
            "-p %s" % self.installdir,
            self.cfg['installopts'],
        ])
        run_shell_cmd(cmd)

    def sanity_check_step(self):
        """Custom sanity check for PALM."""
        custom_paths = {
            'files': [os.path.join(self.installdir, 'bin', 'palmrun')],
            'dirs': [],
        }
        super(EB_PALM, self).sanity_check_step(custom_paths=custom_paths)
