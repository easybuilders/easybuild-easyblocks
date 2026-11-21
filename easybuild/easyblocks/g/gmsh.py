##
# Copyright 2025-2026 Georgios Kafanas
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
EasyBuild support for gmsh, implemented as an easyblock.

@author: Georgios Kafanas (uni.lu)
"""

from easybuild.easyblocks.generic.cmakemake import CMakeMake


class EB_gmsh(CMakeMake):

    def configure_step(self):
        """
        The OpenGL library  provides 2 interfaces,

        * one linking with `libGL.so` (LEGACY), and
        * one linking with `libOpenGL.so` (GLVND).

        The gmsh is configured to build with the LEGACY interface, however, libGLU of
        the foss toolchain uses the GLNVD, and required linking with `libOpenGL.so`.

        This patch sets the CMake policy to use the GLVND so that gmsh builds reliably
        with the toolchain libGLU.

        See: cmake --help-policy CMP0072
        """
        self.cfg.update('configopts', "-DOpenGL_GL_PREFERENCE=GLVND")

        CMakeMake.configure_step(self)
