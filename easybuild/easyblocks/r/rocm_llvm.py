# -*- coding: utf-8 -*-
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
EasyBuild support for building and installing ROCm-LLVM, AMD's fork of the LLVM compiler infrastructure.

@author: Bob Dröge (University of Groningen)
@author: Jan Andre Reuter (jan@zyten.de)
"""
import os
from tempfile import mkdtemp

from easybuild.tools import LooseVersion
from easybuild.easyblocks.llvm import EB_LLVM, BUILD_TARGET_AMDGPU
from easybuild.tools.filetools import apply_regex_substitutions, remove_dir, which, copy_file
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option


class EB_ROCm_minus_LLVM(EB_LLVM):
    """
    Support for building the ROCm-LLVM compilers with some modifications on top of the LLVM easyblock.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Path where the CMakeLists.txt of the 'amdllvm' tool is copied to
        self.amdllvm_cmakelists_copy_path = None

    def _configure_general_build(self):
        super(EB_ROCm_minus_LLVM, self)._configure_general_build()
        self._cmakeopts.update({
            'LLVM_EXTERNAL_PROJECTS': '"device-libs"',
            'LLVM_EXTERNAL_DEVICE_LIBS_SOURCE_DIR': os.path.join(self.llvm_src_dir, 'amd', 'device-libs'),
            'LLVM_ENABLE_PER_TARGET_RUNTIME_DIR': 'ON',
            'CLANG_DEFAULT_RTLIB': 'compiler-rt',
            'CLANG_DEFAULT_UNWINDLIB': 'libgcc',
            'DEFAULT_ROCM_PATH': self.installdir,
            'LIBOMP_COPY_EXPORTS': 'OFF',
            'CLANG_ENABLE_AMDCLANG': 'ON',
        })

        amd_gfx_list = build_option('amdgcn_capabilities', default=[])
        if not amd_gfx_list and 'amdgcn_capabilities' in self.cfg:
            amd_gfx_list = self.cfg['amdgcn_capabilities']
        if not amd_gfx_list and 'AMDGCN_CAPABILITIES' in os.environ:
            amd_gfx_list = os.environ.get('AMDGCN_CAPABILITIES').split(',')
        if not amd_gfx_list:
            raise EasyBuildError("Expected amdgcn_capabilities to be set to build this EasyConfig. "
                                 "Please specify either --amdgcn-capabilities, or set amdgcn_capabilities "
                                 "in the EasyConfig!")
        if LooseVersion('19') <= LooseVersion(self.version) < LooseVersion('20'):
            self.general_opts['LIBOMPTARGET_AMDGCN_GFXLIST'] = self.list_to_cmake_arg(amd_gfx_list)

        # If, for some reason, AMDGPU is missing from LLVM_TARGETS_TO_BUILD, ensure that it is added.
        # If it is missing, the build will fail later on, as the target is expected to exist.
        if BUILD_TARGET_AMDGPU not in self._cmakeopts['LLVM_TARGETS_TO_BUILD']:
            if not self._cmakeopts['LLVM_TARGETS_TO_BUILD'][-1] == ";":
                self._cmakeopts['LLVM_TARGETS_TO_BUILD'] += ";"
            self._cmakeopts['LLVM_TARGETS_TO_BUILD'] += 'AMDGPU'

        intermediate_stage_dir = self.llvm_obj_dir_stage2 if self.cfg['bootstrap'] else self.llvm_obj_dir_stage1
        self.runtimes_cmake_args['AMDDeviceLibs_DIR'] = os.path.join(
            intermediate_stage_dir, 'tools', 'device-libs', 'lib64', 'cmake', 'AMDDeviceLibs'
        )
        self._add_cmake_runtime_args()

    def configure_step(self):
        # the openmp component uses the same build dirs, so we need to remove them to make
        # sure that we start with clean ones
        if os.path.exists(os.path.join(self.builddir, 'llvm.obj.1', 'CMakeCache.txt')):
            remove_dir(os.path.join(self.builddir, 'llvm.obj.1'))
            remove_dir(os.path.join(self.builddir, 'llvm.obj.2'))
            remove_dir(os.path.join(self.builddir, 'llvm.obj.3'))
        super(EB_ROCm_minus_LLVM, self).configure_step()

        if 'openmp' in self.final_projects:
            # fix path to include dir for omp.h:
            omp_header_regex = [(r'\${CMAKE_BINARY_DIR}/projects/openmp/runtime/src',
                                '${CMAKE_BINARY_DIR}/../../projects/openmp/runtime/src')]
            apply_regex_substitutions(os.path.join(self.llvm_src_dir, 'offload',  'DeviceRTL', 'CMakeLists.txt'),
                                      omp_header_regex)

        # ROCm hardcodes the path to the just built Clang. This interferes with our RPATH wrappers.
        # Therefore, patch hardcoded CMAKE_CXX_COMPILER to use our wrappers, if rpath wrapping is enabled.
        # Do NOT simply unset CMAKE_CXX_COMPILER, or else GCC might be picked up if bootstrap is disabled,
        # conflicting with using `-stdlib=libc++`
        if build_option('rpath'):
            self._prepare_runtimes_rpath_wrappers(self.llvm_obj_dir_stage1)
            amdllvm_cmakelists = os.path.join(self.llvm_src_dir, 'clang-tools-extra', 'amdllvm', 'CMakeLists.txt')
            # Copy the original CMakeLists.txt, so that we can restore it in following stages
            tmpdir = mkdtemp("amdllvm-cmakelists-txt-store")
            self.amdllvm_cmakelists_copy_path = f"{tmpdir}/CMakeLists.txt"
            copy_file(amdllvm_cmakelists, self.amdllvm_cmakelists_copy)
            mock_clangxx = which('clang++')
            apply_regex_substitutions(amdllvm_cmakelists,
                                      [(r'set\(CMAKE_CXX_COMPILER ${CMAKE_BINARY_DIR}/bin/clang\+\+\)',
                                        'set(CMAKE_CXX_COMPILER %s)' % mock_clangxx)])

    def build_with_prev_stage(self, prev_dir, stage_dir):
        # Similar handling to case above, just for multi-stage build.
        # Here, we need to create mock wrappers ourselves, as call to LLVM build will start the build process.
        if build_option('rpath'):
            self._prepare_runtimes_rpath_wrappers(stage_dir)
            mock_clangxx = which('clang++')
            # Restore the original file, so that we can replace the Clang with the current stages Clang
            amdllvm_cmakelists = os.path.join(self.llvm_src_dir, 'clang-tools-extra', 'amdllvm', 'CMakeLists.txt')
            copy_file(self.amdllvm_cmakelists_copy_path, amdllvm_cmakelists)
            apply_regex_substitutions(amdllvm_cmakelists,
                                      [(r'set\(CMAKE_CXX_COMPILER ${CMAKE_BINARY_DIR}/bin/clang\+\+\)',
                                        'set(CMAKE_CXX_COMPILER %s)' % mock_clangxx)])

        super(EB_ROCm_minus_LLVM, self).build_with_prev_stage(prev_dir, stage_dir)

    def _configure_final_build(self):
        super(EB_ROCm_minus_LLVM, self)._configure_final_build()
        self._cmakeopts.update({
            'LIBOMP_OMPD_SUPPORT': 'ON',
            # Explicitly disable LIBOMPTARGET_FORCE_DLOPEN_LIBHSA, as this breaks the offload build with OMPT
            # otherwise.
            'LIBOMPTARGET_FORCE_DLOPEN_LIBHSA': 'OFF',
        })
        self._configure_general_build()
