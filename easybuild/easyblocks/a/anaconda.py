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
EasyBuild support for building and installing Anaconda/Miniconda, implemented as an easyblock

@author: Jillian Rowe (New York University Abu Dhabi)
@author: Kenneth Hoste (HPC-UGent)
"""

import os
import stat

from easybuild.easyblocks.generic.binary import Binary
from easybuild.tools.filetools import adjust_permissions, remove_dir
from easybuild.tools.modules import MODULE_LOAD_ENV_HEADERS
from easybuild.tools.run import run_shell_cmd


class EB_Anaconda(Binary):
    """Support for building/installing Anaconda and Miniconda."""

    def __init__(self, *args, **kwargs):
        """Initialize class variables."""
        super().__init__(*args, **kwargs)

        # Do not add installation to search paths for headers or libraries to avoid
        # that the Anaconda environment is used by other software at building or linking time.
        # LD_LIBRARY_PATH issue discusses here:
        # http://superuser.com/questions/980250/environment-module-cannot-initialize-tcl
        mod_env_headers = self.module_load_environment.alias_vars(MODULE_LOAD_ENV_HEADERS)
        mod_env_libs = ['LD_LIBRARY_PATH', 'LIBRARY_PATH']
        mod_env_cmake = ['CMAKE_LIBRARY_PATH', 'CMAKE_PREFIX_PATH']
        for disallowed_var in mod_env_headers + mod_env_libs + mod_env_cmake:
            self.module_load_environment.remove(disallowed_var)
            self.log.debug(f"Purposely not updating ${disallowed_var} in {self.name} module file")

    def install_step(self):
        """Copy all files in build directory to the install directory"""

        remove_dir(self.installdir)
        install_script = self.src[0]['name']

        adjust_permissions(os.path.join(self.builddir, install_script), stat.S_IRUSR | stat.S_IXUSR)

        # Anacondas own install instructions specify "bash [script]" despite using different shebangs
        cmd = "%s bash ./%s -p %s -b -f" % (self.cfg['preinstallopts'], install_script, self.installdir)
        self.log.info("Installing %s using command '%s'..." % (self.name, cmd))
        run_shell_cmd(cmd)

    def sanity_check_step(self):
        """
        Custom sanity check for Anaconda and Miniconda
        """
        custom_paths = {
            'files': [os.path.join('bin', x) for x in ['2to3', 'conda', 'pydoc', 'python', 'sqlite3']],
            'dirs': ['bin', 'etc', 'lib', 'pkgs'],
        }
        super(EB_Anaconda, self).sanity_check_step(custom_paths=custom_paths)
