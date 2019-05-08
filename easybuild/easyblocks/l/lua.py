##
# Copyright 2018-2019 Ghent University
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
EasyBuild support for building and installing Lua, implemented as an easyblock

@author: Ruben Di Battista (Ecole Polytechnique)
@author: Kenneth Hoste (Ghent University)
"""
import os

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.filetools import apply_regex_substitutions


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
        luaconf_h = os.path.join(self.start_dir, 'src', 'luaconf.h')
        self.log.debug("Patching luaconf.h at %s", luaconf_h)
        # note: make sure trailing slash is preserved!
        apply_regex_substitutions(luaconf_h, [(r'/usr/local/', '%s/' % self.installdir)])

        self.cfg.update('buildopts', 'linux')
        self.cfg['runtest'] = 'test'
        self.cfg.update('installopts', 'INSTALL_TOP=%s' % self.installdir)

    def sanity_check_step(self):
        """
        Custom sanity check for Lua.
        """
        custom_paths = {
            'files': ['bin/lua'],
            'dirs': [],
        }
        custom_commands = ["lua -e 'io.write(package.path)' | grep %s" % self.installdir]

        super(EB_Lua, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self):
        """Also define $LUA_DIR in generated module file."""
        txt = super(EB_Lua, self).make_module_extra()

        txt += self.module_generator.set_environment('LUA_DIR', self.installdir)

        return txt
