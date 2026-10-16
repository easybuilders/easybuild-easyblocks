##
# Copyright 2022-2026 Vrije Universiteit Brussel
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
Custom EasyBlock for installing Julia binaries with an extra startup script to give special treatment to.

@author: Davide Grassano (CECAM)
"""
import os
import stat

from easybuild.tools.filetools import write_file, move_file, adjust_permissions
from easybuild.tools.systemtools import get_shared_lib_ext
from easybuild.easyblocks.generic.tarball import Tarball

EB_JULIA_DEPOT_PATH_VAR = "EBJULIA_DEPOT_PATH"
EB_JULIA_LOAD_PATH_VAR = "EBJULIA_LOAD_PATH"

STARTUP_CONTENT = rf"""
# Read EB environment variables
function get_env_list(name)
    haskey(ENV, name) ? split(ENV[name], ':') : []
end

EB_LOAD_PATH = get_env_list("{EB_JULIA_LOAD_PATH_VAR}")
EB_DEPOT_PATH = get_env_list("{EB_JULIA_DEPOT_PATH_VAR}")

# Append EB_LOAD_PATH to the default LOAD_PATH
if !isempty(EB_LOAD_PATH)
    pushfirst!(LOAD_PATH, EB_LOAD_PATH...)
end
# Prepend EB_DEPOT_PATH to the default DEPOT_PATH
if !isempty(EB_DEPOT_PATH)
    push!(DEPOT_PATH, EB_DEPOT_PATH...)
end
"""

WRAPPER_CONTENT = r"""#!/bin/sh
LD_LIBRARY_PATH="$EBROOTJULIA/lib:$EBROOTJULIA/lib/julia:$LD_LIBRARY_PATH" julia.bin "$@"
"""


class EB_Julia(Tarball):
    """Add custom startup script and sanity checks to Julia installations."""

    def sanity_check_step(self):
        """Custom sanity check for Julia."""

        shlib_ext = get_shared_lib_ext()

        custom_files = [
            'bin/julia', 'bin/julia.bin',
            'include/julia/julia.h', f'lib/libjulia.{shlib_ext}', 'etc/julia/startup.jl',
        ]
        custom_dirs = ['bin', 'etc', 'include', 'lib', 'share']
        custom_commands = [
            "julia --help",
            "julia --version",
            "julia -E '1+2 == 3' | grep true",
        ]
        custom_paths = {
            'files': custom_files,
            'dirs': custom_dirs,
        }

        super().sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def install_step(self, *args, **kwargs):
        """Install procedure for Julia."""
        super().install_step(*args, **kwargs)

        startup_script = os.path.join(self.installdir, 'etc', 'julia', 'startup.jl')
        os.makedirs(os.path.dirname(startup_script), exist_ok=True)

        write_file(startup_script, STARTUP_CONTENT)
        julia_bin = os.path.join(self.installdir, 'bin', 'julia')
        julia_bin_new = os.path.join(self.installdir, 'bin', 'julia.bin')

        # install wrapper with linking safeguards for Julia libraries
        move_file(julia_bin, julia_bin_new)
        write_file(julia_bin, WRAPPER_CONTENT)
        adjust_permissions(julia_bin, stat.S_IRUSR | stat.S_IXUSR)
