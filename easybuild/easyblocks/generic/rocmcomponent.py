##
# Copyright 2009-2026 Ghent University
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
from easybuild.toolchains.compiler.rocm_compilers import ROCmCompilers
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
            'ignore_system_rocm': [True, "Ignore system ROCm installation", CUSTOM],
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

        # Allow the EasyConfig with a non-native toolchain. This is only really useful if one
        # wants to build the EasyConfig with ROCm-LLVM / LLVM and place the result still in e.g.
        # GCCcore.
        # Another usecase is software requiring 'hipcc' to build, with it being used as their C++
        # compiler.
        if self.cfg['compiler_toolchain'] != TOOLCHAIN_DEFAULT:
            # Determine which compilers to use instead. Make sure that they are actually available.
            # Check for the modules they should be located in.
            if self.cfg['compiler_toolchain'] == TOOLCHAIN_ROCM_LLVM:
                rocm_llvm_root = get_software_root('ROCm-LLVM')
                if not rocm_llvm_root:
                    raise EasyBuildError(f"ROCm-LLVM is required to build {self.cfg.name}")
                tmp_toolchain = ROCmCompilers(name='ROCmCompilers', version='1')
            elif self.cfg['compiler_toolchain'] == TOOLCHAIN_HIPCC:
                hip_root = get_software_root('HIP')
                if not hip_root:
                    raise EasyBuildError(f"HIP is required to build {self.cfg.name} with hipcc / hipfc")
                tmp_toolchain = ROCmCompilers(name='ROCmCompilers', version='1')
                tmp_toolchain.COMPILER_CC = 'hipcc'
                tmp_toolchain.COMPILER_CXX = 'hipcc'
                # TODO: Add compiler wrappers for Fortran via hipfc once EasyConfigs are available.
                # hipfc needs basically all math libraries for proper support.
                # For now, fall back to amdflang.
                # tmp_toolchain.COMPILER_F77 = 'hipfc'
                # tmp_toolchain.COMPILER_F90 = 'hipfc'
                # tmp_toolchain.COMPILER_FC = 'hipfc'
            elif self.cfg['compiler_toolchain'] == TOOLCHAIN_LLVM:
                # This is meant to represent a vanilla LLVM, not the adapted ROCm-LLVM.
                # Especially important if one builds ROCm components with CUDA support, which
                # does not require any ROCm-LLVM components.
                llvm_root = get_software_root('LLVM')
                if not llvm_root:
                    raise EasyBuildError(f"LLVM is required to build {self.cfg.name}")
                tmp_toolchain = Clang(name='Clang', version='1')
            else:
                raise EasyBuildError(f"Unknown compiler toolchain {self.cfg['compiler_toolchain']}")

            # RPATH wrappers are put in place only for the default toolchain. If we're using different compilers to
            # build this RocmComponent, we have to put the RPATH wrappers in place here, in the easyblock
            if build_option('rpath'):
                tmp_toolchain.prepare_rpath_wrappers()

                # RPATH wrappers add -Wl,rpath arguments to all command lines, including when it is just compiling
                # Clang by default warns about that, and then some configure tests use -Werror which turns those
                # warnings into errors. As a result, those configure tests fail, even though the compiler supports the
                # requested functionality (e.g. the test that checks if -fPIC is supported would fail, and it compiles
                # without resulting in relocation errors).
                # See https://github.com/easybuilders/easybuild-easyblocks/pull/2799#issuecomment-1270621100
                # Here, we add -Wno-unused-command-line-argument to CXXFLAGS to avoid these warnings alltogether
                cflags = os.getenv('CFLAGS', '')
                cxxflags = os.getenv('CXXFLAGS', '')
                setvar('CFLAGS', "%s %s" % (cflags, '-Wno-unused-command-line-argument'))
                setvar('CXXFLAGS', "%s %s" % (cxxflags, '-Wno-unused-command-line-argument'))

            mock_cc = which(tmp_toolchain.COMPILER_CC)
            mock_cxx = which(tmp_toolchain.COMPILER_CXX)
            mock_fc = which(tmp_toolchain.COMPILER_FC)
            mock_hip = which(tmp_toolchain.COMPILER_CXX)

            self.cfg['configopts'] += f'-DCMAKE_C_COMPILER={mock_cc} '
            self.cfg['configopts'] += f'-DCMAKE_CXX_COMPILER={mock_cxx} '
            self.cfg['configopts'] += f'-DCMAKE_HIP_COMPILER={mock_hip} '
            self.cfg['configopts'] += f'-DCMAKE_Fortran_COMPILER={mock_fc} '

        self.cfg['configopts'] += f'-DHIP_PLATFORM={self.cfg["hip_platform"]} '
        amd_gfx_list = build_option('amdgcn_capabilities') or self.cfg['amdgcn_capabilities'] or []
        if amd_gfx_list and self.cfg['hip_platform'] == HIP_PLATFORM_AMD:
            # For now, pass both AMDGPU_TARGETS and GPU_TARGETS, until AMD finally drops the former for all packages.
            self.cfg['configopts'] += f'-DAMDGPU_TARGETS={self.list_to_cmake_arg(amd_gfx_list)} '
            self.cfg['configopts'] += f'-DGPU_TARGETS={self.list_to_cmake_arg(amd_gfx_list)} '
        if self.cfg['ignore_system_rocm']:
            self.cfg['configopts'] += "-DCMAKE_IGNORE_PREFIX_PATH=/opt/rocm "
        super().configure_step(srcdir, builddir)
