##
# Copyright 2019-2019 Ghent University
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
EasyBuild support for building and installing Flang, implemented as an easyblock

@author: Alan O'Cais (Juelich Supercomputing Centre)
"""
import glob
import os
import shutil
from distutils.version import LooseVersion

from easybuild.easyblocks.c.clang import EB_Clang
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import change_dir, copy_file, mkdir, move_file
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_Flang(EB_Clang):
    """Support for bootstrapping Flang."""

    def disable_sanitizer_tests(self):
        # Not relevant for flang
        pass

    def extract_step(self):
        """
        Prepare a combined (Flang fork) LLVM source tree.  The layout is:
        llvm/             Unpack flang-llvm-*.tar.gz here
          projects/
            openmp/       Unpack openmp-*.tar.xz here
          tools/
            clang/        Unpack flang-flang-driver*.tar.gz here (yes, it does need to be called 'clang'!)
        """

        # Extract everything into separate directories.
        super(EB_Clang, self).extract_step()

        # Find the full path to the directory that was unpacked from flang-llvm-*.tar.gz
        for srcfile in self.src:
            if srcfile['name'].startswith("flang-llvm-"):
                self.llvm_src_dir = srcfile['finalpath']
                break

        if self.llvm_src_dir is None:
            raise EasyBuildError(
                "Could not determine LLVM source root (LLVM source was not unpacked?)")
        src_dirs = {}

        def find_source_dir(globpattern, targetdir):
            """Search for directory with globpattern and rename it to targetdir"""
            glob_src_dirs = [glob_dir for glob_dir in glob.glob(globpattern)]
            if len(glob_src_dirs) == 1:
                src_dirs[glob_src_dirs[0]] = targetdir
            else:
                raise EasyBuildError("Failed to find exactly one source directory for pattern %s: %s",
                                     globpattern, glob_src_dirs)


        if LooseVersion(self.version) >= LooseVersion('3.8'):
            find_source_dir('openmp-*',
                            os.path.join(self.llvm_src_dir, 'projects', 'openmp'))

        find_source_dir('flang-driver-*',
                        os.path.join(self.llvm_src_dir, 'tools', 'clang'))

        # Place the flang code in a separate directory for the build step for after
        # we've built llvm
        self.flang_source_dir = os.path.join(os.path.dirname(self.llvm_src_dir), 'flang')
        find_source_dir('flang-flang_*', self.flang_source_dir)

        moved_sources = 0
        for src in self.src:
            for (dirname, new_path) in src_dirs.items():
                if src['name'].startswith(dirname):
                    old_path = os.path.join(src['finalpath'], dirname)
                    move_file(old_path, new_path)
                    # count moved sources
                    moved_sources += 1
                    break
        # Verify that all of the unpacked sources (except the llvm source) were moved
        moved_sources_message = "%d of %d unpacked source directories were moved." % (moved_sources, len(self.src))
        if len(self.src) - 1 == moved_sources:
            self.log.info(moved_sources_message)
        else:
            raise EasyBuildError(moved_sources_message)

    def build_with_temporary_llvm(self, build_dir, src_dir, parallel=True, additional_options=[]):
        """Build Clang stage N using Clang stage N-1"""

        # Create and enter build directory.
        mkdir(build_dir)
        change_dir(build_dir)

        # Configure.
        CC = os.path.join(self.llvm_obj_dir, 'bin', 'clang')
        CXX = os.path.join(self.llvm_obj_dir, 'bin', 'clang++')
        FC = os.path.join(self.llvm_obj_dir, 'bin', 'flang')
        LLVM_CONFIG = os.path.join(self.llvm_obj_dir, 'bin', 'llvm-config')
        shlib_ext = get_shared_lib_ext()
        LIBOMP = os.path.join(self.llvm_obj_dir, 'lib', 'libomp.%s' % shlib_ext)

        opts_map = {
            'CMAKE_INSTALL_PREFIX': self.installdir,
            'CMAKE_C_COMPILER': CC,
            'CMAKE_CXX_COMPILER': CXX,
            'CMAKE_Fortran_COMPILER': FC,
            # Tell it where to find our temporary LLVM installation
            'LLVM_CONFIG': LLVM_CONFIG,
            # Say which OMP runtime to use
            'FLANG_LIBOMP': LIBOMP
        }
        options = ' '.join('-D%s=%s' % item for item in sorted(opts_map.items()))
        options += ' ' + ' '.join(additional_options) + ' ' + self.cfg['configopts']

        self.log.info("Configuring")
        run_cmd("cmake %s %s" % (options, src_dir), log_all=True)

        self.log.info("Building")
        cmd = 'make'
        if parallel:
            cmd += ' ' + self.make_parallel_opts
        run_cmd(cmd, log_all=True)

    def build_step(self):
        # First build llvm and the driver
        super(EB_Flang, self).build_step()
        if self.cfg['bootstrap']:
            self.llvm_obj_dir = self.llvm_obj_dir_stage3
        else:
            self.llvm_obj_dir = self.llvm_obj_dir_stage1

        # Build libpgmath with the temporary llvm
        self.pgmath_build_dir = os.path.join(self.builddir, 'pgmath_obj')
        self.build_with_temporary_llvm(
            self.pgmath_build_dir,
            os.path.join(self.flang_source_dir, 'runtime', 'libpgmath')
            )
        # Build flang with the temporary llvm
        self.flang_build_dir = os.path.join(self.builddir, 'flang_obj')
        shlib_ext = get_shared_lib_ext()
        self.build_with_temporary_llvm(
            self.flang_build_dir,
            self.flang_source_dir,
            parallel=False,  # Can misbehave in parallel
            additional_options=[
                '-DLIBPGMATH=%s' % os.path.join(self.pgmath_build_dir, 'lib', 'libpgmath.%s' % shlib_ext),
                # Ensure libraries are rpath-ed to the install directory (most relevant for libomp.so link)
                '-DCMAKE_BUILD_WITH_INSTALL_RPATH=1',
                '-DCMAKE_INSTALL_RPATH=%s' % os.path.join(self.installdir, 'lib'),
            ]
        )

    def install_step(self):
        """Install flang binaries and necessary libraries."""
        shlib_ext = get_shared_lib_ext()
        change_dir(self.pgmath_build_dir)
        super(EB_Clang, self).install_step()
        change_dir(self.flang_build_dir)
        super(EB_Clang, self).install_step()
        # Copy over the flang executable from LLVM
        copy_file(
            os.path.join(self.llvm_obj_dir, 'bin', 'flang'),
            os.path.join(self.installdir, 'bin', 'flang'),
        )
        # Also copy over the libomp libraries
        copy_file(
            os.path.join(self.llvm_obj_dir, 'lib', 'libomp.%s' % shlib_ext),
            os.path.join(self.installdir, 'lib'),
        )

    def sanity_check_step(self):
        """Custom sanity check for Flang."""
        shlib_ext = get_shared_lib_ext()
        custom_paths = {
            'files': [
                # flang related
                "bin/flang", "bin/flang1", "bin/flang2",
                "include/ieee_arithmetic.mod", "include/ieee_exceptions.mod", "include/ieee_features.mod",
                "include/iso_c_binding.mod", "include/iso_fortran_env.mod",
                "lib/libflang.a", "lib/libflang.%s" % shlib_ext, "lib/libflangmain.a", "lib/libflangrti.a",
                "lib/libflangrti.%s" % shlib_ext,
                # OpenMP related
                "include/omp_lib.h", "include/omp_lib_kinds.mod", "include/omp_lib.mod",
                "lib/libomp.%s" % shlib_ext, "lib/libompstub.a", "lib/libompstub.%s" % shlib_ext,
                # libpgmath related
                "lib/libpgmath.a", "lib/libpgmath.%s" % shlib_ext],
            'dirs': [],
        }
        super(EB_Clang, self).sanity_check_step(custom_paths=custom_paths)
