##
# Copyright 2009-2024 Ghent University
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
EasyBuild support for Blender, implemented as an easyblock

@author: Samuel Moors (Vrije Universiteit Brussel)
"""
import os

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.tools.filetools import find_glob_pattern
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_Blender(CMakeMake):
    """Support for building Blender."""

    @staticmethod
    def extra_options():
        extra_vars = CMakeMake.extra_options()
        extra_vars['separate_build_dir'][0] = True
        return extra_vars

    def configure_step(self):
        """Set CMake options for Blender"""

        default_config_opts = {
            'WITH_BUILDINFO': 'OFF',
            # disable SSE detection to give EasyBuild full control over optimization compiler flags being used
            'WITH_CPU_SSE': 'OFF',
            # needed unless extra dependencies are added for it to work
            'WITH_GAMEENGINE': 'OFF',
            'WITH_INSTALL_PORTABLE': 'OFF',
            # needed unless extra dependencies are added for it to work
            'WITH_SYSTEM_GLEW': 'OFF',
        }

        for key in default_config_opts:
            opt = '-D%s=' % key
            if opt not in self.cfg['configopts']:
                self.cfg.update('configopts', opt + default_config_opts[key])

        # Python paths
        python_root = get_software_root('Python')
        if python_root:
            shlib_ext = get_shared_lib_ext()
            pyshortver = '.'.join(get_software_version('Python').split('.')[:2])
            site_packages = os.path.join(python_root, 'lib', 'python%s' % pyshortver, 'site-packages')

            # We assume that numpy/requests are included with the Python installation (no longer true for 2019a)
            numpy_root = find_glob_pattern(
                os.path.join(site_packages, 'numpy-*-py%s-linux-x86_64.egg' % pyshortver))
            requests_root = find_glob_pattern(os.path.join(site_packages, 'requests-*-py%s.egg' % pyshortver))
            python_lib = find_glob_pattern(
                os.path.join(python_root, 'lib', 'libpython%s*.%s' % (pyshortver, shlib_ext)))
            python_include_dir = find_glob_pattern(os.path.join(python_root, 'include', 'python%s*' % pyshortver))

            self.cfg.update('configopts', '-DPYTHON_VERSION=%s' % pyshortver)
            self.cfg.update('configopts', '-DPYTHON_LIBRARY=%s' % python_lib)
            self.cfg.update('configopts', '-DPYTHON_INCLUDE_DIR=%s' % python_include_dir)
            self.cfg.update('configopts', '-DPYTHON_NUMPY_PATH=%s' % numpy_root)
            self.cfg.update('configopts', '-DPYTHON_REQUESTS_PATH=%s' % requests_root)

        # OpenEXR
        openexr_root = get_software_root('OpenEXR')
        if openexr_root:
            self.cfg.update('configopts', '-DOPENEXR_INCLUDE_DIR=%s' % os.path.join(openexr_root, 'include'))

        # OpenColorIO
        if get_software_root('OpenColorIO'):
            self.cfg.update('configopts', '-DWITH_OPENCOLORIO=ON')

        # CUDA
        if get_software_root('CUDA'):
            self.cfg.update('configopts', '-DWITH_CYCLES_CUDA_BINARIES=ON')

        super(EB_Blender, self).configure_step()

    def sanity_check_step(self):
        """Custom sanity check for Blender."""
        custom_paths = {
            'files': ['bin/blender'],
            'dirs': [],
        }

        # make sure Cycles render engine is available
        custom_commands = ["blender -b -E help | grep CYCLES"]

        super(EB_Blender, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
