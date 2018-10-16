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
EasyBuild support for installing compiler toolchains, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""

from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.toolchain.utilities import get_toolchain, search_toolchain


class Toolchain(Bundle):
    """
    Compiler toolchain: generate module file only, nothing to build/install
    """
    @staticmethod
    def extra_options():
        extra_vars = {
            'set_build_env': [True, "Include statements to prepare the environment for using this toolchain " \
                                     "(e.g. $CC, $CFLAGS, etc.) in the generated module file", CUSTOM],
        }
        return Bundle.extra_options(extra_vars)

    def make_module_extra(self):
        """
        Include statements to prepare environment for using this toolchain (if desired).
        """
        txt = super(Toolchain, self).make_module_extra()

        tc_spec = {'name': self.name, 'version': self.version}
        tcdeps = self.cfg.dependencies()
        tc_inst = get_toolchain(tc_spec, {}, tcdeps=tcdeps, modtool=self.modules_tool)
        tc_inst.add_dependencies(tcdeps)
        tc_inst._load_dependencies_modules()
        tc_inst.set_variables()
        self._add_dependency_variables()
        tc_inst.generate_vars()
        for key, val in sorted(tc_inst.vars.items()):
            txt += self.module_generator.set_environment(key, val)

        return txt
