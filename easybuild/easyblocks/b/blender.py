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
EasyBuild support for Blender, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Ward Poelmans (Ghent University)
@author: Samuel Moors (Vrije Universiteit Brussel)
"""
import glob
import os

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_Blender(CMakeMake):
    """Support for building Blender."""

    def configure_step(self):
        """Set CMake options for Blender"""
        self.cfg['separate_build_dir'] = True

        self.cfg.update('configopts', '-DWITH_INSTALL_PORTABLE=OFF')
        self.cfg.update('configopts', '-DWITH_BUILDINFO=OFF')

        # disable SSE detection to give EasyBuild full control over optimization compiler flags being used
        self.cfg.update('configopts', '-DWITH_CPU_SSE=OFF')
        self.cfg.update('configopts', '-DCMAKE_C_FLAGS_RELEASE="-DNDEBUG"')
        self.cfg.update('configopts', '-DCMAKE_CXX_FLAGS_RELEASE="-DNDEBUG"')

        # these are needed until extra dependencies are added for them to work
        self.cfg.update('configopts', '-DWITH_GAMEENGINE=OFF')
        self.cfg.update('configopts', '-DWITH_SYSTEM_GLEW=OFF')

        # Python paths
        python_root = get_software_root('Python')
        pyshortver = '.'.join(get_software_version('Python').split('.')[:2])
        site_packages = os.path.join(python_root, 'lib', 'python%s' % pyshortver, 'site-packages')
        numpy_root = glob.glob(os.path.join(site_packages, 'numpy*'))[0]
        requests_root = glob.glob(os.path.join(site_packages, 'requests*'))[0]
        shlib_ext = get_shared_lib_ext()
        self.cfg.update('configopts', '-DPYTHON_VERSION=%s' % pyshortver)
        self.cfg.update('configopts', '-DPYTHON_LIBRARY=%s/lib/libpython%sm.%s' % (python_root, pyshortver, shlib_ext))
        self.cfg.update('configopts', '-DPYTHON_INCLUDE_DIR=%s/include/python%sm' % (python_root, pyshortver))
        self.cfg.update('configopts', '-DPYTHON_NUMPY_PATH=%s' % numpy_root)
        self.cfg.update('configopts', '-DPYTHON_REQUESTS_PATH=%s' % requests_root)

        # OpenEXR
        self.cfg.update('configopts', '-DOPENEXR_INCLUDE_DIR=$EBROOTOPENEXR/include')

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

        super(EB_Blender, self).sanity_check_step(custom_paths=custom_paths)
