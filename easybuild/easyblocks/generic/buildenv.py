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

from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.tools.config import build_option, update_build_option
from easybuild.tools.toolchain.toolchain import RPATH_WRAPPERS_SUBDIR


class BuildEnv(Bundle):
    """
    Build environment of toolchain: only generate module file
    """

    def prepare_step(self, *args, **kwargs):
        """
        Custom prepare step for buildenv: export rpath wrappers if they are being used
        """
        # We export the rpath wrappers under special conditions
        # (the wrappers are needed if LD_LIBRARY_PATH is being filtered)
        filtered_env_vars = build_option('filter_env_vars') or []
        if build_option('rpath') and 'LD_LIBRARY_PATH' in filtered_env_vars and 'LIBRARY_PATH' not in filtered_env_vars:
            # re-create installation dir (deletes old installation),
            self.make_installdir()
            # then set keeppreviousinstall to True (to avoid deleting wrappers we create)
            self.cfg['keeppreviousinstall'] = True

            # Temporarily unset the rpath setting so that we can control the rpath wrapper creation
            update_build_option('rpath', False)

            # Prepare the toolchain, we need to export the wrappers _after_ the modules have been loaded
            # (so that correct compilers are defined)
            super(BuildEnv, self).prepare_step(*args, **kwargs)

            # export the rpath wrappers
            self.toolchain.prepare_rpath_wrappers(
                rpath_filter_dirs=kwargs.get('rpath_filter_dirs', None),
                rpath_include_dirs=kwargs.get('rpath_include_dirs', None),
                wrappers_dir=os.path.join(self.installdir, 'bin'),
                add_to_path=True,
                disable_wrapper_log=True
                )

            # Restore the rpath option
            update_build_option('rpath', True)
        else:
            super(BuildEnv, self).prepare_step(*args, **kwargs)

    def make_module_extra(self):
        """Add all the build environment variables."""
        txt = super(BuildEnv, self).make_module_extra()

        # include environment variables defined for (non-system) toolchain
        if not self.toolchain.is_system_toolchain():
            for key, val in sorted(self.toolchain.vars.items()):
                txt += self.module_generator.set_environment(key, val)

        self.log.debug("make_module_extra added this: %s" % txt)
        return txt

    def make_module_step(self, fake=False):
        """Specify correct bin directories for buildenv installation."""
        filtered_env_vars = build_option('filter_env_vars') or []
        if build_option('rpath') and 'LD_LIBRARY_PATH' in filtered_env_vars and 'LIBRARY_PATH' not in filtered_env_vars:
            wrappers_dir = os.path.join(self.installdir, 'bin', RPATH_WRAPPERS_SUBDIR)
            if os.path.exists(wrappers_dir):
                wrappers_dir_subdirs = [os.path.join(wrappers_dir, dir) for dir in os.listdir(wrappers_dir)]
                if wrappers_dir_subdirs:
                    self.module_load_environment.PATH = wrappers_dir_subdirs

        return super(BuildEnv, self).make_module_step(fake=fake)
