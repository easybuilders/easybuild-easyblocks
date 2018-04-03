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
EasyBuild support for software that uses the GNU installation procedure,
i.e. configure/make/make install, implemented as an easyblock.

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Toon Willems (Ghent University)
"""
import fileinput
import os
import re
import sys

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.run import run_cmd
from easybuild.tools.build_log import EasyBuildError


class EB_Lua(ConfigureMake):
    """
    Support for building and installing Lua
    """

    def configure_step(self, cmd_prefix=''):
        """
        Configure step

        Lua does not need a configure step. In this step we just patch the
        `luaconf.h` file in the sources to point to the correct Lua Root
        """

        src_dir = self.src[0]['finalpath']

        luaconf_h = os.path.join(src_dir, 'src', 'luaconf.h')

        # Open file
        self.log.debug("Patching luaconf.h at {}".format(luaconf_h))
        for line in fileinput.input(luaconf_h, inplace=True):
            if line.startswith('#define LUA_ROOT'):
                installdir = os.path.join(self.installdir, '')  # Add trailing slash
                line = re.sub(r'/usr/local/', installdir, line)
            sys.stdout.write(line)

    def test_step(self):
        out = super(EB_Lua, self).test_step()

        # Check if the path where lua looks for packages is correctly pointing
        # to installdir
        cmd = "src/lua -e 'io.write(package.path)'"

        stdout, exitcode = run_cmd(cmd, log_all=True, simple=False)

        if not(self.installdir in stdout):
            raise EasyBuildError("package.path seems to not point in the right path")

        return out

    def install_step(self):
        """
        Create the installation in correct location
        - typical: make install
        """

        cmd = "%s make install INSTALL_TOP=%s %s" % (self.cfg['preinstallopts'],
                                                     self.install_subdir, self.cfg['installopts'])

        (out, _) = run_cmd(cmd, log_all=True, simple=False)

        return out
