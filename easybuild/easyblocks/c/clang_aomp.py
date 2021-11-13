# -*- coding: utf-8 -*-
##
# Copyright 2009-2021 Ghent University
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
EasyBuild support for building and installing AOMP version of LLVM/Clang

@author: Jørgen Nordmoen (University of Oslo, USIT)
"""
import glob
import os

from easybuild.easyblocks.clang import DEFAULT_TARGETS_MAP as LLVM_ARCH_MAP
from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_msg, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.modules import get_software_root
from easybuild.tools.systemtools import AARCH64, POWER, X86_64
from easybuild.tools.systemtools import get_cpu_architecture, get_shared_lib_ext


# Default AMD GPU architectures to build for
DEFAULT_GFX_ARCHS = ['gfx900', 'gfx902', 'gfx906', 'gfx908', 'gfx90a', 'gfx1030', 'gfx1031']


class EB_Clang_AOMP(Bundle):
    """
    Self-contained build of AOMP version of Clang
    """

    @staticmethod
    def extra_options():
        extra_vars = {
            'gfx_list': [[], "AMD GPU architectures to build for", CUSTOM],
        }
        return Bundle.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        super(EB_Clang_AOMP, self).__init__(*args, **kwargs)
        # List of LLVM target architectures to build for, extended in the 'prepare_step'
        self.target_archs = ['AMDGPU']
        # Mapping from known ROCm components to their configure method
        self.cfg_method = {
            'llvm-project': self._configure_llvm,
            'ROCm-Device-Libs': self._configure_device_libs,
            'Clang-OpenMP': self._configure_omp,
            'aomp-extras': self._configure_aomp_extras,
        }
        # Prepare configuration options that point to the expected Clang build
        self.llvm_compiler_flags = [
            "-DCMAKE_C_COMPILER=%s" % os.path.join(self.installdir, 'bin', 'clang'),
            "-DCMAKE_CXX_COMPILER=%s" % os.path.join(self.installdir, 'bin', 'clang++'),
            "-DLLVM_INSTALL_PREFIX=%s" % self.installdir,
            "-DLLVM_DIR=%s" % self.installdir,
        ]
        # Variables to be filled in the prepare step
        self.amd_gfx_archs = []
        self.cuda_archs = []
        self.device_lib_path = None

    def prepare_step(self, *args, **kwargs):
        """
        Setup target architectures for LLVM
        """
        super(EB_Clang_AOMP, self).prepare_step(*args, **kwargs)
        # Detect CPU architecture and setup build targets for LLVM
        cpu_arch = get_cpu_architecture()
        if cpu_arch not in LLVM_ARCH_MAP:
            raise EasyBuildError('Unknown CPU architecture for LLVM: %s' % cpu_arch)
        self.target_archs.append(LLVM_ARCH_MAP[cpu_arch][0])
        # If CUDA is loaded when building, try to build CUDA offload backend
        if get_software_root('CUDA'):
            self.target_archs.append('NVPTX')
            ec_cuda_cc = self.cfg['cuda_compute_capabilities']
            cfg_cuda_cc = build_option('cuda_compute_capabilities')
            cuda_cc = cfg_cuda_cc or ec_cuda_cc or []
            if not cuda_cc:
                raise EasyBuildError("Can't build Clang-AOMP with CUDA support "
                                     "without specifying 'cuda-compute-capabilities'")
            self.cuda_archs = [cc.replace('.', '') for cc in cuda_cc]
            self.log.info("Building offload support for the following CUDA architectures: '%s'",
                          ' '.join(self.amd_gfx_archs))
        self.log.info("Building LLVM for the following architectures: '%s'", ';'.join(self.target_archs))
        # Setup AMD GFX list to build for
        if self.cfg['gfx_list']:
            self.amd_gfx_archs = self.cfg['gfx_list']
        else:
            self.amd_gfx_archs = DEFAULT_GFX_ARCHS
        self.log.info("Building offload support for the following AMD architectures: '%s'",
                      ' '.join(self.amd_gfx_archs))
        # Ensure necessary libraries are downloaded and can be found
        device_lib_dir_pattern = os.path.join(self.builddir, 'ROCm-Device-Libs-*')
        hits = glob.glob(device_lib_dir_pattern)
        if len(hits) == 1:
            self.device_lib_path = hits[0]
        else:
            raise EasyBuildError("Could not find 'ROCm-Device-Libs' source directory")

    def configure_step(self):
        """
        Go through each component and setup configuration for the later Bundle install step
        """
        super(EB_Clang_AOMP, self).configure_step()

        num_comps = len(self.cfg['components'])
        for idx, comp in enumerate(self.comp_cfgs):
            name = comp['name']
            msg = "configuring bundle component %s %s (%d/%d)..." % (name, comp['version'], idx + 1, num_comps)
            print_msg(msg)
            if name in self.cfg_method:
                self.cfg_method[name](comp)
                self.log.info(msg)
            else:
                self.log.warn("Component %s has no configure method!" % name)

    def sanity_check_step(self):
        """
        Custom sanity check for ROCm
        """
        shlib_ext = get_shared_lib_ext()
        custom_paths = {
            'files': ['bin/clang', 'bin/lld', 'lib/libomp.%s' % shlib_ext,
                      'lib/libomptarget.rtl.amdgpu.%s' % shlib_ext, 'lib/libomptarget.%s' % shlib_ext],
            'dirs': ['amdgcn/bitcode', 'include/clang', 'include/lld', 'include/llvm',
                     'lib/libdevice'],
        }
        custom_commands = ['clang --help', 'clang++ --help']
        # Check that all AMD GFX libraries were built
        for gfx in self.amd_gfx_archs:
            custom_paths['files'].append('lib/libdevice/libomptarget-amdgcn-%s.bc' % gfx)
            custom_paths['files'].append('lib/libdevice/libaompextras-amdgcn-%s.bc' % gfx)
            custom_paths['files'].append('lib/libdevice/libm-amdgcn-%s.bc' % gfx)
        # Check that CPU target OpenMP offloading library was built
        arch = get_cpu_architecture()
        # Check architecture explicitly since Clang uses potentially
        # different names
        if arch == X86_64:
            arch = 'x86_64'
        elif arch == POWER:
            arch = 'ppc64'
        elif arch == AARCH64:
            arch = 'aarch64'
        else:
            print_warning("Unknown CPU architecture (%s) for OpenMP offloading!" % arch)
        custom_paths['files'].append('lib/libomptarget.rtl.%s.%s' % (arch, shlib_ext))
        # If CUDA offloading support was requested, check that correct omptarget was built
        if get_software_root('CUDA'):
            custom_paths['files'].append('lib/libomptarget.rtl.cuda.%s' % shlib_ext)
            for arch in self.cuda_archs:
                sm_arch = 'sm_%s' % arch
                custom_paths['files'].append('lib/libdevice/libomptarget-nvptx-%s' % sm_arch)
                custom_paths['files'].append('lib/libdevice/libaompextras-nvptx-%s' % sm_arch)
                custom_paths['files'].append('lib/libdevice/libm-nvptx-%s' % sm_arch)
        super(EB_Clang_AOMP, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def _configure_llvm(self, component):
        """
        Setup configure options for building compiler_rt, Clang and lld
        """
        comp_dir = '%s-%s' % (component['name'], component['version'])
        component['srcdir'] = os.path.join(comp_dir, 'llvm')
        # Need to unset $CPATH to avoid that libunwind is pulled in via Mesa
        # dependency and interrupts building of LLVM
        component['prebuildopts'] = "unset CPATH && "
        # Setup configuration options for LLVM
        component['configopts'] = "-DLLVM_ENABLE_PROJECTS='clang;lld;compiler-rt' "
        component['configopts'] += "-DCLANG_DEFAULT_LINKER=lld "
        component['configopts'] += "-DGCC_INSTALL_PREFIX=$EBROOTGCC "
        component['configopts'] += "-DLLVM_ENABLE_ASSERTIONS=ON "
        component['configopts'] += "-DLLVM_ENABLE_BINDINGS=OFF "
        component['configopts'] += "-DLLVM_INCLUDE_BENCHMARKS=OFF "
        component['configopts'] += "-DLLVM_TARGETS_TO_BUILD='%s'" % ';'.join(self.target_archs)

    def _configure_device_libs(self, component):
        """
        Setup device libs such that it is built with the local LLVM build
        """
        component['configopts'] = ' '.join(self.llvm_compiler_flags)
        component['configopts'] += " -DBUILD_HC_LIB=OFF"

    def _configure_omp(self, component):
        """
        Setup OpenMP configuration options, OMP uses the LLVM source
        """
        llvm_include_dir = os.path.join(self.installdir, 'include', 'llvm')
        comp_dir = 'llvm-project-%s' % component['version']
        component['srcdir'] = os.path.join(comp_dir, 'openmp')
        component['preconfigopts'] = "export HSA_RUNTIME_PATH=%s && " % self.installdir
        component['configopts'] = " ".join(self.llvm_compiler_flags)
        component['configopts'] += " -DLIBOMPTARGET_AMDGCN_GFXLIST='%s'" % ';'.join(self.amd_gfx_archs)
        component['configopts'] += " -DLIBOMPTARGET_ENABLE_DEBUG=ON"
        component['configopts'] += " -DLIBOMPTARGET_LLVM_INCLUDE_DIRS=%s" % llvm_include_dir
        component['configopts'] += " -DLIBOMP_COPY_EXPORTS=OFF"
        component['configopts'] += " -DLLVM_MAIN_INCLUDE_DIR=%s" % llvm_include_dir
        component['configopts'] += " -DOPENMP_ENABLE_LIBOMPTARGET=ON"
        component['configopts'] += " -DOPENMP_ENABLE_LIBOMPTARGET_HSA=ON"
        component['configopts'] += " -DROCDL=%s" % self.device_lib_path
        component['configopts'] += " -DROCM_DIR=%s" % self.installdir
        component['configopts'] += " -DAOMP_STANDALONE_BUILD=1"
        if get_software_root('CUDA'):
            llvm_link = os.path.join(self.installdir, 'bin', 'llvm-link')
            cuda_path = os.path.join(self.installdir, 'bin', 'clang++')
            component['configopts'] += " -DLIBOMPTARGET_NVPTX_BC_LINKER=%s" % llvm_link
            component['configopts'] += " -DLIBOMPTARGET_NVPTX_COMPUTE_CAPABILITIES='%s'" % ','.join(self.cuda_archs)
            component['configopts'] += " -DLIBOMPTARGET_NVPTX_CUDA_COMPILER=%s" % cuda_path
            component['configopts'] += " -DLIBOMPTARGET_NVPTX_ENABLE_BCLIB=ON"

    def _configure_aomp_extras(self, component):
        """
        Setup AOMP extras compiler configurations
        """
        component['preconfigopts'] = "export AOMP=%s && " % self.installdir
        component['preconfigopts'] += "export GFXLIST='%s' && " % ';'.join(self.amd_gfx_archs)
        component['configopts'] = " ".join(self.llvm_compiler_flags)
        component['configopts'] += " -DAOMP_STANDALONE_BUILD=1"
        component['configopts'] += " -DROCDL=%s" % self.device_lib_path
        component['configopts'] += " -DROCM_DIR=%s" % self.installdir
