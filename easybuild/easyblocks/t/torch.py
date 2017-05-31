##
# Copyright 2009-2017 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
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
EasyBuild support for Torch, implemented as an easyblock

@author: Maxime Boissonneault (Compute Canada)
"""
import os
import re

from distutils.version import LooseVersion

import easybuild.tools.toolchain as toolchain
import easybuild.tools.environment as env
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd


class EB_Torch(CMakeMake):
    """Support for building Torch."""

    @staticmethod
    def extra_options():
        """Add extra config options specific to Torch."""
        extra_vars = {
            'with_magma' : [False, "Builds with Magma support", CUSTOM]
        }
        return CMakeMake.extra_options(extra_vars)

    def configure_step(self):
        """Set some extra environment variables before configuring."""

        # compiler flags
        cflags = [os.getenv('CFLAGS')]
        cxxflags = [os.getenv('CXXFLAGS')]
        fflags = [os.getenv('FFLAGS')]
        mklroot = [os.getenv('MKLROOT')]

        self.cfg.update('configopts', '-DCMAKE_C_FLAGS="%s"' % ' '.join(cflags))
        self.cfg.update('configopts', '-DCMAKE_CXX_FLAGS="%s"' % ' '.join(cxxflags))
        self.cfg.update('configopts', '-DCMAKE_Fortran_FLAGS="%s"' % ' '.join(fflags))
        # it does not find mkl automatically, so we provide the paths
        self.cfg.update('configopts', '-DCMAKE_INCLUDE_PATH=%s/include ' % mklroot)
        self.cfg.update('configopts', '-DCMAKE_LIBRARY_PATH=%s/lib/intel64 ' % mklroot)
       
        # enable luajit21
        self.cfg.update('configopts', '-DWITH_LUAJIT21=ON')

        # configure using cmake
        super(EB_Torch, self).configure_step()

    def build_step(self):
        """Build with make (verbose logging enabled)."""
        super(EB_Torch, self).build_step(verbose=True)

    def extensions_step(self):
        fake_mod_data = None
        if not self.dry_run:
            fake_mod_data = self.load_fake_module(purge=True)

            # also load modules for build dependencies again, since those are not loaded by the fake module
#            self.modules_tool.load(dep['short_mod_name'] for dep in self.cfg['builddependencies'])

            ext_list = [
                { "dir": "extra/luafilesystem", "spec": "rockspecs/luafilesystem-1.6.3-1.rockspec" },
                { "dir": "extra/penlight", "spec": "" },
                { "dir": "extra/lua-cjson", "spec": "" },
                { "dir": "extra/luaffifb", "spec": "" },
                { "dir": "pkg/sundown", "spec": "rocks/sundown-scm-1.rockspec" },
                { "dir": "pkg/cwrap", "spec": "rocks/cwrap-scm-1.rockspec" },
                { "dir": "pkg/paths", "spec": "rocks/paths-scm-1.rockspec" },
                { "dir": "pkg/torch", "spec": "rocks/torch-scm-1.rockspec" },
                { "dir": "pkg/dok", "spec": "rocks/dok-scm-1.rockspec" },
                { "dir": "exe/trepl", "spec": "" },
                { "dir": "pkg/sys", "spec": "sys-1.1-0.rockspec" },
                { "dir": "pkg/xlua", "spec": "xlua-1.0-0.rockspec" },
                { "dir": "extra/nn", "spec": "rocks/nn-scm-1.rockspec" },
                { "dir": "extra/graph", "spec": "rocks/graph-scm-1.rockspec" },
                { "dir": "extra/nngraph", "spec": "" },
                { "dir": "pkg/image", "spec": "image-1.1.alpha-0.rockspec" },
                { "dir": "pkg/optim", "spec": "optim-1.0.5-0.rockspec" },
                { "dir": "pkg/gnuplot", "spec": "rocks/gnuplot-scm-1.rockspec" },
                { "dir": "exe/env", "spec": "" },
                { "dir": "extra/nnx", "spec": "nnx-0.1-1.rockspec" },
                { "dir": "extra/threads", "spec": "rocks/threads-scm-1.rockspec" },
                { "dir": "extra/argcheck", "spec": "rocks/argcheck-scm-1.rockspec" },
                ]

            if self.cfg["with_magma"]:
                ext_list = ext_list + [
                    { "dir": "extra/cutorch", "spec": "rocks/cutorch-scm-1.rockspec" },
                    { "dir": "extra/cunn", "spec": "rocks/cunn-scm-1.rockspec" },
                    { "dir": "extra/cudnn", "spec": "cudnn-scm-1.rockspec" }
                    ]
                magma_root = get_software_root("magma", with_env_var=False)
                # we need to modify the FindMAGMA.cmake to find the right path because it otherwise searches in /usr/local
                cmd = """sed -i "s;/usr/local/magma/;%s;g" %s/torch/extra/cutorch/lib/THC/cmake/FindMAGMA.cmake""" % (magma_root, self.builddir)
                (out, _) = run_cmd(cmd, log_all=True, simple=False)


            # the extensions use cmake to build, and won't find libraries unless we define CMAKE_xxx_PATH.
            env.setvar('CMAKE_INCLUDE_PATH',os.getenv('CPATH'))
            env.setvar('CMAKE_LIBRARY_PATH',os.getenv('LIBRARY_PATH'))
            for item in ext_list:
                cmd = """cd %(builddir)s/torch/%(directory)s; %(installdir)s/bin/luarocks make %(spec)s""" % {
                        'builddir': self.builddir,
                        'installdir': self.installdir,
                        'directory': item["dir"],
                        'spec': item["spec"]
                    }
                (out, _) = run_cmd(cmd, log_all=True, simple=False)

        super(EB_Torch, self).extensions_step()


    def sanity_check_step(self):
        """Custom sanity check for Torch."""
        libs = [ 'luajit', 'luaT', 'THC', 'TH' ]
        custom_paths = {
            'files': [os.path.join('lib', 'lib%s.so' % x) for x in libs],
            'dirs': ['bin', 'etc', 'include', 'lib', 'share', 'include/TH', 'include/THC', 'share/cmake']
        }

        super(EB_Torch, self).sanity_check_step(custom_paths=custom_paths)
