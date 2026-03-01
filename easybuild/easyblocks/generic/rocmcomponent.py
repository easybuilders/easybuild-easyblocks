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
EasyBuild support for ROCm components, having a similar build structure,
implemented as an easyblock

@author: Jan Andre Reuter (jan@zyten.de)
"""
import os

from easybuild.framework.easyconfig import CUSTOM
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.toolchains.compiler.clang import Clang
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import which
from easybuild.tools.modules import get_software_root
from easybuild.tools.environment import setvar


HIP_PLATFORM_AMD = "amd"
HIP_PLATFORM_NVIDIA = "nvidia"

TOOLCHAIN_ROCM_LLVM = "rocm-llvm"
TOOLCHAIN_LLVM = "llvm"
TOOLCHAIN_HIPCC = "hipcc"
TOOLCHAIN_DEFAULT = "default"


class ROCmComponent(CMakeMake):
    """Support for building ROCm components"""

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters for ROCmComponent"""
        extra_vars = CMakeMake.extra_options(extra_vars)
        extra_vars.update({
            'compiler_toolchain': [TOOLCHAIN_DEFAULT, f"Select toolchain to build the package. "
                                                      f"Allowed values: {TOOLCHAIN_DEFAULT}, {TOOLCHAIN_ROCM_LLVM}, "
                                                      f"{TOOLCHAIN_LLVM}, {TOOLCHAIN_HIPCC}", CUSTOM],
            'hip_platform': [HIP_PLATFORM_AMD, f"Specify HIP platform. "
                                               f"Allowed values: {HIP_PLATFORM_AMD}, {HIP_PLATFORM_NVIDIA}", CUSTOM],
        })
        return extra_vars

    def configure_step(self, srcdir=None, builddir=None):
        """Prepare configuration to properly build ROCm component."""

        # If HIP platform is chosen to be nvidia, CUDA should be present in dependencies
        if self.cfg['hip_platform'] == HIP_PLATFORM_NVIDIA:
            cuda_root = get_software_root('CUDA')
            if not cuda_root:
                raise EasyBuildError(f"CUDA is required to build {self.cfg.name} with NVIDIA GPU support!")
        elif self.cfg['hip_platform'] == HIP_PLATFORM_AMD:
            rocm_llvm_root = get_software_root('ROCm-LLVM')
            if not rocm_llvm_root:
                raise EasyBuildError(f"ROCm-LLVM is required to build {self.cfg.name} with AMD GPU support!")
        else:
            raise EasyBuildError("hip_platform parameter contains non-allowed value.")

        if self.cfg['compiler_toolchain'] != TOOLCHAIN_DEFAULT:
            if build_option('rpath'):
                tmp_toolchain = Clang(name='Clang', version='1')
                if self.cfg['compiler_toolchain'] == TOOLCHAIN_ROCM_LLVM:
                    tmp_toolchain.COMPILER_CC = 'clang'
                    tmp_toolchain.COMPILER_CXX = 'clang++'
                elif self.cfg['compiler_toolchain'] == TOOLCHAIN_HIPCC:
                    tmp_toolchain.COMPILER_CC = 'hipcc'
                    tmp_toolchain.COMPILER_CXX = 'hipcc'
                tmp_toolchain.prepare_rpath_wrappers()

                cflags = os.getenv('CFLAGS', '')
                cxxflags = os.getenv('CXXFLAGS', '')
                setvar('CFLAGS', "%s %s" % (cflags, '-Wno-unused-command-line-argument'))
                setvar('CXXFLAGS', "%s %s" % (cxxflags, '-Wno-unused-command-line-argument'))

            if self.cfg['compiler_toolchain'] == TOOLCHAIN_ROCM_LLVM:
                amdclang_mock = which('clang')
                amdclangxx_mock = which('clang++')
            elif self.cfg['compiler_toolchain'] == TOOLCHAIN_HIPCC:
                amdclang_mock = which('hipcc')
                amdclangxx_mock = which('hipcc')

            self.cfg['configopts'] += f'-DCMAKE_C_COMPILER={amdclang_mock} '
            self.cfg['configopts'] += f'-DCMAKE_CXX_COMPILER={amdclangxx_mock} '
            self.cfg['configopts'] += f'-DCMAKE_HIP_COMPILER={amdclangxx_mock} '

        self.cfg['configopts'] += f'-DHIP_PLATFORM={self.cfg["hip_platform"]} '
        amd_gfx_list = build_option('amdgcn_capabilities') or self.cfg['amdgcn_capabilities'] or []
        if amd_gfx_list and self.cfg['hip_platform'] == HIP_PLATFORM_AMD:
            # For now, pass both AMDGPU_TARGETS and GPU_TARGETS, until AMD finally drops the former for all packages.
            self.cfg['configopts'] += f'-DAMDGPU_TARGETS={self.list_to_cmake_arg(amd_gfx_list)} '
            self.cfg['configopts'] += f'-DGPU_TARGETS={self.list_to_cmake_arg(amd_gfx_list)} '
        super().configure_step(srcdir, builddir)
