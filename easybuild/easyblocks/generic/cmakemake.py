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
EasyBuild support for software that is configured with CMake, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Ward Poelmans (Ghent University)
@author: Maxime Boissonneault (Compute Canada - Universite Laval)
"""
import os

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.config import build_option
from easybuild.tools.filetools import change_dir, mkdir, which
from easybuild.tools.environment import setvar
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd
from easybuild.tools.utilities import nub


DEFAULT_CONFIGURE_CMD = 'cmake'


class CMakeMake(ConfigureMake):
    """Support for configuring build with CMake instead of traditional configure script"""

    @staticmethod
    def extra_options(extra_vars=None):
        """Define extra easyconfig parameters specific to CMakeMake."""
        extra_vars = ConfigureMake.extra_options(extra_vars)
        extra_vars.update({
            'abs_path_compilers': [False, "Specify compilers via absolute file path (not via command names)", CUSTOM],
            'allow_system_boost': [False, "Always allow CMake to pick up on Boost installed in OS "
                                          "(even if Boost is included as a dependency)", CUSTOM],
            'configure_cmd': [DEFAULT_CONFIGURE_CMD, "Configure command to use", CUSTOM],
            'srcdir': [None, "Source directory location to provide to cmake command", CUSTOM],
            'separate_build_dir': [False, "Perform build in a separate directory", CUSTOM],
        })
        return extra_vars

    def configure_step(self, srcdir=None, builddir=None):
        """Configure build using cmake"""

        # Set the search paths for CMake
        tc_ipaths = self.toolchain.get_variable("CPPFLAGS", list)
        tc_lpaths = self.toolchain.get_variable("LDFLAGS", list)
        cpaths = os.getenv('CPATH', '').split(os.pathsep)
        lpaths = os.getenv('LD_LIBRARY_PATH', '').split(os.pathsep)
        include_paths = os.pathsep.join(nub(tc_ipaths + cpaths))
        library_paths = os.pathsep.join(nub(tc_lpaths + lpaths))
        setvar("CMAKE_INCLUDE_PATH", include_paths)
        setvar("CMAKE_LIBRARY_PATH", library_paths)

        if builddir is None and self.cfg.get('separate_build_dir', False):
            builddir = os.path.join(self.builddir, 'easybuild_obj')

        if builddir:
            mkdir(builddir, parents=True)
            change_dir(builddir)
            default_srcdir = self.cfg['start_dir']
        else:
            default_srcdir = '.'

        if srcdir is None:
            if self.cfg.get('srcdir', None) is not None:
                srcdir = self.cfg['srcdir']
            else:
                srcdir = default_srcdir

        options = ['-DCMAKE_INSTALL_PREFIX=%s' % self.installdir]
        env_to_options = {
            'CC': 'CMAKE_C_COMPILER',
            'CFLAGS': 'CMAKE_C_FLAGS',
            'CXX': 'CMAKE_CXX_COMPILER',
            'CXXFLAGS': 'CMAKE_CXX_FLAGS',
            'F90': 'CMAKE_Fortran_COMPILER',
            'FFLAGS': 'CMAKE_Fortran_FLAGS',
        }
        for env_name, option in env_to_options.items():
            value = os.getenv(env_name)
            if value is not None:
                if option.endswith('_COMPILER') and self.cfg.get('abs_path_compilers', False):
                    value = which(value)
                    self.log.info("Using absolute path to compiler command: %s", value)
                options.append("-D%s='%s'" % (option, value))

        if build_option('rpath'):
            # instruct CMake not to fiddle with RPATH when --rpath is used, since it will undo stuff on install...
            # https://github.com/LLNL/spack/blob/0f6a5cd38538e8969d11bd2167f11060b1f53b43/lib/spack/spack/build_environment.py#L416
            options.append('-DCMAKE_SKIP_RPATH=ON')

        # show what CMake is doing by default
        options.append('-DCMAKE_VERBOSE_MAKEFILE=ON')

        if not self.cfg.get('allow_system_boost', False):
            # don't pick up on system Boost if Boost is included as dependency
            # - specify Boost location via -DBOOST_ROOT
            # - instruct CMake to not search for Boost headers/libraries in other places
            # - disable search for Boost CMake package configuration file
            boost_root = get_software_root('Boost')
            if boost_root:
                options.extend([
                    '-DBOOST_ROOT=%s' % boost_root,
                    '-DBoost_NO_SYSTEM_PATHS=ON',
                    '-DBoost_NO_BOOST_CMAKE=ON',
                ])

        options_string = ' '.join(options)

        if self.cfg.get('configure_cmd') == DEFAULT_CONFIGURE_CMD:
            command = ' '.join([
                    self.cfg['preconfigopts'],
                    DEFAULT_CONFIGURE_CMD,
                    options_string,
                    self.cfg['configopts'],
                    srcdir])
        else:
            command = ' '.join([
                    self.cfg['preconfigopts'],
                    self.cfg.get('configure_cmd'),
                    self.cfg['configopts']])

        (out, _) = run_cmd(command, log_all=True, simple=False)

        return out
