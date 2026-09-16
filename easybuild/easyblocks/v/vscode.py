##
# Copyright 2012-2026 Ghent University
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
EasyBlock for installing VSCode and code-cli, implemented as an easyblock
@author: Alan O'Cais (Juelich Supercomputing Centre)
@author: Alex Domingo (Vrije Universiteit Brussel)
"""

from easybuild.easyblocks.generic.tarball import Tarball
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.systemtools import AARCH64, X86_64, get_cpu_architecture


class EB_VSCode(Tarball):
    """
    Support for installing VSCode and code-cli.
    """

    def __init__(self, *args, **kwargs):
        """ Init the easyblock adding a new mapped_arch template var """
        myarch = get_cpu_architecture()
        if myarch == X86_64:
            self.mapped_arch = 'x64'
        elif myarch == AARCH64:
            self.mapped_arch = 'arm64'
        else:
            raise EasyBuildError(f"Architecture {myarch} is not supported for {self.name} on EasyBuild")

        super().__init__(*args, **kwargs)

        self.cfg.template_values['mapped_arch'] = self.mapped_arch
        self.cfg.generate_template_values()

        # installation type: supports VSCode (default) and code-cli
        self.install_type = 'vscode'
        if self.name == 'code-cli':
            self.install_type = 'code-cli'

        # location of VSCode executables:
        bin_path = {
            'vscode': 'bin',  # {installdir}/bin
            'code-cli': '',  # {installdir}
        }
        try:
            self.module_load_environment.PATH = bin_path[self.install_type]
        except KeyError as err:
            raise EasyBuildError(f"Unknown binary location for {self.name} in VSCode easyblock") from err

    def sanity_check_step(self):
        """Custom sanity check for VSCode and code-cli."""
        vscode_paths = {
            'vscode': {
                'files': ['bin/code', 'bin/code-tunnel', 'code'],
                'dirs': ['locales', 'resources'],
            },
            'code-cli': {
                'files': ['code'],
                'dirs': [],
            },
        }
        try:
            custom_paths = vscode_paths[self.install_type]
        except KeyError as err:
            raise EasyBuildError(f"Unknown sanity checks for {self.name} in VSCode easyblock") from err

        custom_commands = ["code --version"]

        return super().sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
