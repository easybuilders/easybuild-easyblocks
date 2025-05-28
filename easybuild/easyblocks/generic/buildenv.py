##
# Copyright 2015-2025 Ghent University
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
EasyBuild support for creating a module that loads the build
environment flags for the current toolchain

@author: Alan O'Cais (Juelich Supercomputing Centre)
"""
import os
import stat

from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.tools.filetools import adjust_permissions, copy_dir
from easybuild.tools.toolchain.toolchain import RPATH_WRAPPERS_SUBDIR


class BuildEnv(Bundle):
    """
    Build environment of toolchain: only generate module file
    """

    def prepare_step(self, *args, **kwargs):
        """
        Custom prepare step for buildenv: export rpath wrappers if they are being used
        """
        # passed to toolchain.prepare to specify location for RPATH wrapper scripts (if RPATH linking is enabled)
        self.rpath_wrappers_dir = self.builddir

        super(BuildEnv, self).prepare_step(*args, **kwargs)

    def install_step(self, *args, **kwargs):
        """
        Custom install step for buildenv: copy RPATH wrapper scripts to install dir, if desired
        """
        super(BuildEnv, self).install_step(*args, **kwargs)

        # copy RPATH wrapper scripts to install directory (if they exist)
        wrappers_dir = os.path.join(self.rpath_wrappers_dir, RPATH_WRAPPERS_SUBDIR)
        if os.path.exists(wrappers_dir):
            self.rpath_wrappers_dir = os.path.join(self.installdir, 'bin')
            copy_dir(wrappers_dir, os.path.join(self.rpath_wrappers_dir, RPATH_WRAPPERS_SUBDIR))
            # Make sure wrappers are readable/executable by everyone
            adjust_permissions(
                self.rpath_wrappers_dir,
                stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                )

    def make_module_extra(self):
        """Add all the build environment variables."""
        txt = super().make_module_extra()

        # include environment variables defined for (non-system) toolchain
        if not self.toolchain.is_system_toolchain():
            for key, val in sorted(self.toolchain.vars.items()):
                txt += self.module_generator.set_environment(key, val)

        self.log.debug(f"make_module_extra added this: {txt}")
        return txt

    def make_module_step(self, fake=False):
        """Specify correct bin directories for buildenv installation."""
        wrappers_dir = os.path.join(self.rpath_wrappers_dir, RPATH_WRAPPERS_SUBDIR)
        if os.path.exists(wrappers_dir):
            self.module_load_environment.PATH = [os.path.join(wrappers_dir, d) for d in os.listdir(wrappers_dir)]

        return super(BuildEnv, self).make_module_step(fake=fake)
