# -*- coding: utf-8 -*-
##
# Copyright 2009-2026 Ghent University
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
EasyBuild support for building and installing tmpi, implemented as an easyblock

@author: Georgios Kafanas (University of Luxembourg)
@author: Bob Dröge (University of Groningen)
"""

from easybuild.easyblocks.generic.cmdcp import CmdCp
from easybuild.tools.build_log import print_warning, EasyBuildError
from easybuild.framework.easyconfig import CUSTOM


class EB_tmpi(CmdCp):

    @staticmethod
    def extra_options(extra_vars=None):
        """Change default values of options"""
        extra = CmdCp.extra_options()
        # files_to_copy is not mandatory here
        extra['files_to_copy'][2] = CUSTOM

        return extra

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cfg['skipsteps'] = ['build']
        self.cfg['files_to_copy'] = [
            (['tmpi'], 'bin'),
        ]

    def prepare_step(self, *args, **kwargs):
        dep_names = [dep['name'] for dep in self.cfg['dependencies']]

        if 'tmux' not in dep_names and 'tmux' not in self.cfg['osdependencies']:
            self.cfg['osdependencies'].append('tmux')
            print_warning(
                "tmux is not in the dependencies or the osdependencies list of %s; adding tmux in the osdependencies.",
                self.name,
                log=self.log
            )

        super().prepare_step(*args, **kwargs)

    def configure_step(self):
        """
        tmpi does not check dependencies during installation or sanity checks;
        if dependencies are not checked explicitly, then the program will fail at runtime.
        """
        required_deps = ('GDB',)
        deps = [dep['name'] for dep in self.cfg['dependencies']]

        missing_deps = [pkg for pkg in required_deps if pkg not in deps]

        if missing_deps:
            raise EasyBuildError(
                "Missing required dependencies for %s: %s",
                self.name,
                ', '.join(missing_deps)
            )

        if self.toolchain.mpi_family() is None:
            raise EasyBuildError(
                "Toolchain %s for %s is not supporting MPI".
                self.toolchain.name,
                self.name
            )

    def sanity_check_step(self):
        custom_paths = {
            'files': ['bin/%(name)s'],
            'dirs': [],
        }
        custom_commands = [
            r"tmpi | grep -E 'tmpi\ \[number\]\ \[command\]'",
        ]

        super().sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
