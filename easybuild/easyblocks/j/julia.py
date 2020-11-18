##
# Copyright 2009-2019 Ghent University
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
EasyBuild support for building and installing Julia packages, implemented as an easyblock

@author: Victor Holanda (CSCS)
@author: Samuel Omlin (CSCS)
@author: Bart Oldeman (McGill University, Calcul Quebec, Compute Canada)
"""
import os
import shutil
import socket

from easybuild.tools.config import build_option
from easybuild.framework.easyconfig import CUSTOM
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import mkdir
from easybuild.tools.run import run_cmd, parse_log_for_error
from easybuild.tools import systemtools


class EB_Julia(ConfigureMake):
    """
    Install an Julia package as a separate module, or as an extension.
    """
    @staticmethod
    def extra_options(extra_vars=None):
        extra_vars = {
            'arch_name': [None, "Change julia's Project.toml pathname", CUSTOM],
        }
        return ConfigureMake.extra_options(extra_vars)


    def get_environment_folder(self):
        env_path = ''

        hostname = socket.gethostname()
        hostname_short = ''.join(c for c in hostname if not c.isdigit())

        if self.cfg['arch_name']:
            env_path = '-'.join([hostname_short, self.cfg['arch_name']])
            return env_path

        optarch = build_option('optarch') or None
        if optarch:
            env_path = '-'.join([hostname_short, optarch])
        else:
            arch = systemtools.get_cpu_architecture()
            cpu_family = systemtools.get_cpu_family()
            env_path = '-'.join([hostname_short, cpu_family, arch])
        return env_path

    def get_user_depot_path(self):
        user_depot_path = ''

        hostname = socket.gethostname()
        hostname_short = ''.join(c for c in hostname if not c.isdigit())

        optarch = build_option('optarch') or None
        if optarch:
            user_depot_path = os.path.join('~', '.julia', self.version, self.get_environment_folder())
        else:
            arch = systemtools.get_cpu_architecture()
            cpu_family = systemtools.get_cpu_family()
            user_depot_path = os.path.join('~', '.julia', self.version, self.get_environment_folder())
        return user_depot_path

    def __init__(self, *args, **kwargs):
        """Initliaze RPackage-specific class variables."""
        super(EB_Julia, self).__init__(*args, **kwargs)

        arch_map = {
            "sse3": ("nocona", ""),
            "avx": ("sandybridge", "OPENBLAS_TARGET_ARCH=SANDYBRIDGE"),
            "avx2": ("haswell", "OPENBLAS_TARGET_ARCH=HASWELL"),
            "avx512": ("skx", "OPENBLAS_TARGET_ARCH=SKYLAKEX"),
        }
        target, openblas = arch_map[os.getenv('RSNT_ARCH')]
        for opts in "buildopts", "installopts":
            self.cfg.update(opts, "prefix=%s" % self.installdir)
            self.cfg.update(opts, "USE_BINARYBUILDER=0")
            # Specifying JULIA_CPU_TARGET allows use on non-identical CPUs.  Doesn't affect JIT or linked toolchain components.
            self.cfg.update(opts, "JULIA_CPU_TARGET=%s" % target)
            self.cfg.update(opts, openblas)

        self.user_depot = self.get_user_depot_path()
        extensions_depot = os.path.join(self.installdir, 'extensions')
        local_share_depot = os.path.join(self.installdir, 'local', 'share', 'julia')
        share_depot = os.path.join(self.installdir, 'share', 'julia')
        self.admin_depots = ':'.join([extensions_depot, local_share_depot, share_depot])
        self.julia_depot_path = ':'.join([self.user_depot, self.admin_depots])

        self.julia_project = os.path.join(self.user_depot, "environments", '-'.join([self.version, self.get_environment_folder()]))

        self.user_load_path = '@:@#.#.#-%s' % self.get_environment_folder()
        self.admin_load_path = '%s:@stdlib' % os.path.join(extensions_depot, "environments", '-'.join([self.version, self.get_environment_folder()]))
        self.julia_load_path = ':'.join([self.user_load_path, self.admin_load_path])

    def configure_step(self):
        """No custom configure step for Julia"""
        pass

    def sanity_check_step(self):
        """Custom sanity check for Julia."""

        custom_paths = {
            'files': [os.path.join('bin', 'julia')],
            'dirs': ['bin', 'include', 'lib', 'share'],
        }
        custom_commands = [
            "julia --version",
            "julia --eval '1+2'",
        ]

        super(EB_Julia, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def install_step(self, *args, **kwargs):
        """Install procedure for Julia"""

        super(EB_Julia, self).install_step(*args, **kwargs)
        txt = """
# depot path modifications
if haskey(ENV, "EBJULIA_USER_DEPOT_PATH")
    USER_DEPOT_PATH  = split(ENV["EBJULIA_USER_DEPOT_PATH"],':')
else
    USER_DEPOT_PATH = []
end
if haskey(ENV, "EBJULIA_ADMIN_DEPOT_PATH")
    ADMIN_DEPOT_PATH = split(ENV["EBJULIA_ADMIN_DEPOT_PATH"],':')
else
    ADMIN_DEPOT_PATH = []
end

if (length(DEPOT_PATH) != length(USER_DEPOT_PATH) + length(ADMIN_DEPOT_PATH))
    error("There is an error in your configuration of the DEPOT_PATH; please contact your support team.")
end

DEPOT_PATH .= [USER_DEPOT_PATH; ADMIN_DEPOT_PATH]

# load path modifications
if haskey(ENV, "EBJULIA_USER_LOAD_PATH")
    USER_LOAD_PATH  = split(ENV["EBJULIA_USER_LOAD_PATH"],':')
else
    USER_LOAD_PATH  = []
end

if haskey(ENV, "EBJULIA_ADMIN_LOAD_PATH")
    ADMIN_LOAD_PATH = split(ENV["EBJULIA_ADMIN_LOAD_PATH"],':')
else
    ADMIN_LOAD_PATH  = []
end

if (length(LOAD_PATH) != length(USER_LOAD_PATH) + length(ADMIN_LOAD_PATH))
    error("There is an error in your configuration of the LOAD_PATH; please contact your support team.\nLOAD_PATH: $LOAD_PATH\nUSER_LOAD_PATH: $USER_LOAD_PATH\nADMIN_LOAD_PATH: $ADMIN_LOAD_PATH")
    #error("There is an error in your configuration of the LOAD_PATH; please contact your support team.")
end

LOAD_PATH .= [USER_LOAD_PATH; ADMIN_LOAD_PATH]
        """
        with open(os.path.join(self.installdir, 'etc', 'julia', 'startup.jl'), 'w') as startup_file:
            startup_file.write(txt)
            startup_file.close()

    def make_module_extra(self, *args, **kwargs):
        txt = super(EB_Julia, self).make_module_extra(*args, **kwargs)

        txt += self.module_generator.set_environment('JULIA_PROJECT', self.julia_project)

        txt += self.module_generator.set_environment('JULIA_DEPOT_PATH', self.julia_depot_path)
        txt += self.module_generator.set_environment('EBJULIA_USER_DEPOT_PATH', self.user_depot)
        txt += self.module_generator.set_environment('EBJULIA_ADMIN_DEPOT_PATH', self.admin_depots)


        txt += self.module_generator.set_environment('JULIA_LOAD_PATH', self.julia_load_path)
        txt += self.module_generator.set_environment('EBJULIA_USER_LOAD_PATH', self.user_load_path)
        txt += self.module_generator.set_environment('EBJULIA_ADMIN_LOAD_PATH', self.admin_load_path)

        txt += self.module_generator.set_environment('EBJULIA_ENV_NAME', '-'.join([self.version, self.get_environment_folder()]))

        return txt

