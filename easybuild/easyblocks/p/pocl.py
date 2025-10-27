##
# Copyright 2009-2025 Ghent University
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
EasyBuild support for pocl, implemented as an easyblock

@author: Petr Král (INUITS)
"""
from easybuild.easyblocks.generic.cmakeninja import CMakeNinja
from easybuild.tools.run import run_shell_cmd


class EB_pocl(CMakeNinja):
    """Support for building pocl."""

    def configure_step(self, *args, **kwargs):
        """
        Try to configure without `DLLC_HOST_CPU=native` but in case it fails,
        avoid host CPU auto-detection (which may fail on recent CPUs)
        """
        command = ' '.join([
                "mkdir build &&",
                "cd build &&",
                self.cfg['preconfigopts'],
                "cmake -G Ninja ",
                self.cfg['configopts'],
                "&& cd -"])
        res = run_shell_cmd(command, fail_on_error=False)
        if res.exit_code != 0:
            self.cfg.update('configopts', 'DLLC_HOST_CPU=native')
        CMakeNinja.configure_step(self, *args, **kwargs)
