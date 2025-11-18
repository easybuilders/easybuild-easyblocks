##
# Copyright 2016-2025 Ghent University
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
EasyBuild support for building and installing Kokkos, implemented as an easyblock

@author: Jan Reuter (JSC)
"""
from easybuild.tools import LooseVersion

import easybuild.tools.toolchain as toolchain
from easybuild.base import fancylogger
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.modules import get_software_root
from easybuild.tools.systemtools import AARCH64, get_cpu_architecture
from easybuild.tools.toolchain.compiler import OPTARCH_GENERIC

from easybuild.easyblocks.generic.cmakemake import CMakeMake

KOKKOS_INTEL_PACKAGE_ARCH_LIST = [
    'WSM',  # Intel Westmere CPU (SSE 4.2), removed in Kokkos 4.3
    'SNB',  # Intel Sandy/Ivy Bridge CPU (AVX 1)
    'HSW',  # Intel Haswell CPU (AVX 2)
    'BDW',  # Intel Broadwell Xeon E-class CPU (AVX 2 + transactional mem)
    'SKL',  # Intel Skylake Client CPU
    'SKX',  # Intel Sky Lake Xeon E-class HPC CPU (AVX512 + transactional mem)
    'ICL',  # Intel Ice Lake Client CPU (AVX512)
    'ICX',  # Intel Ice Lake Xeon Server CPU (AVX512)
    'SPR',  # Intel Sapphire Rapids Xeon Server CPU (AVX512)
    'KNC',  # Intel Knights Corner Xeon Phi
    'KNL',  # Intel Knights Landing Xeon Phi
]

KOKKOS_CPU_ARCH_LIST = [
    'NATIVE'  # Local CPU architecture
    'AMDAVX',  # AMD 64-bit x86 CPU (AVX 1)
    'ZEN',  # AMD Zen class CPU (AVX 2)
    'ZEN2',  # AMD Zen2 class CPU (AVX 2)
    'ZEN3',  # AMD Zen3 class CPU (AVX 2)
    'ZEN4',  # AMD Zen4 class CPU (AVX-512), since Kokkos 4.6
    'ZEN5',  # AMD Zen5 class CPU (AVX-512), since Kokkos 4.7
    'ARMV80',  # ARMv8.0 Compatible CPU
    'ARMV81',  # ARMv8.1 Compatible CPU
    'ARMV8_THUNDERX',  # ARMv8 Cavium ThunderX CPU
    'ARMV8_THUNDERX2',  # ARMv8 Cavium ThunderX2 CPU
    'A64FX',  # ARMv8.2 with SVE Support
    'ARMV9_GRACE',  # ARMv9 NVIDIA Grace CPU, since Kokkos 4.4.1
    'BGQ',  # IBM Blue Gene/Q CPU
    'POWER7',  # IBM POWER7 CPU
    'POWER8',  # IBM POWER8 CPU
    'POWER9',  # IBM POWER9 CPU
    'RISCV_SG2042',  # RISC-V SG2042 CPU, since Kokkos 4.3
    'RISCV_RVA22V',  # RISC-V RVA22V CPU, since Kokkos 4.5
    'RISCV_U74MC',  # RISC-V U74MC, since Kokkos 4.7

    'KEPLER30',  # NVIDIA Kepler generation CC 3.0 GPU, removed in Kokkos 5.0
    'KEPLER32',  # NVIDIA Kepler generation CC 3.2 GPU, removed in Kokkos 5.0
    'KEPLER35',  # NVIDIA Kepler generation CC 3.5 GPU, removed in Kokkos 5.0
    'KEPLER37',  # NVIDIA Kepler generation CC 3.7 GPU, removed in Kokkos 5.0
    'MAXWELL50',  # NVIDIA Maxwell generation CC 5.0 GPU
    'MAXWELL52',  # NVIDIA Maxwell generation CC 5.2 GPU
    'MAXWELL53',  # NVIDIA Maxwell generation CC 5.3 GPU
    'PASCAL60',  # NVIDIA Pascal generation CC 6.0 GPU
    'PASCAL61',  # NVIDIA Pascal generation CC 6.1 GPU
    'VOLTA70',  # NVIDIA Volta generation CC 7.0 GPU
    'VOLTA72',  # NVIDIA Volta generation CC 7.2 GPU
    'TURING75',  # NVIDIA Turing generation CC 7.5 GPU
    'AMPERE80',  # NVIDIA Ampere generation CC 8.0 GPU
    'AMPERE86',  # NVIDIA Ampere generation CC 8.6 GPU
    'ADA89',  # NVIDIA Ada Lovelace generation CC 8.9 GPU, since Kokkos 4.1
    'HOPPER90',  # NVIDIA Hopper generation CC 9.0 GPU, since Kokkos 4.0
    'BLACKWELL100',  # NVIDIA Blackwell generation CC 10.0 GPU, since Kokkos 4.7
    'BLACKWELL120',  # NVIDIA Blackwell generation CC 12.0 GPU, since Kokkos 4.7

    'AMD_GFX906',  # AMD GPU MI50/MI60, since Kokkos 4.2
    'AMD_GFX908',  # AMD GPU MI100, since Kokkos 4.2
    'AMD_GFX90A',  # AMD GPU MI200, since Kokkos 4.2
    'AMD_GFX942',  # AMD GPU MI300, since Kokkos 4.2
    'AMD_GFX942_APU',  # AMD APU MI300A, since Kokkos 4.5
    'AMD_GFX1030',  # AMD GPU V620/W6800, since Kokkos 4.2
    'AMD_GFX1100',  # AMD GPU RX7900XTX, since Kokkos 4.2
    'AMD_GFX1103',  # AMD APU Phoenix, since Kokkos 4.5
    'AMD_GFX1201',  # AMD AI PRO R9700, Radeon RX 9070 XT, since Kokkos 5.0

    'INTEL_GEN',  # Intel GPUs Gen9+
    'INTEL_DG1',  # Intel Iris XeMAX GPU
    'INTEL_GEN9',  # Intel GPU Gen9
    'INTEL_GEN11',  # Intel GPU Gen11
    'INTEL_GEN12LP',  # Intel GPU Gen12LP
    'INTEL_XEHP',  # Intel GPUs Xe-HP
    'INTEL_PVC',  # Intel GPU Ponte Vecchio
    'INTEL_DG2',  # Intel GPU DG2, since Kokkos 4.7
] + KOKKOS_INTEL_PACKAGE_ARCH_LIST


KOKKOS_GPU_ARCH_TABLE = {
    '3.0': 'KEPLER30',  # NVIDIA Kepler generation CC 3.0
    '3.2': 'KEPLER32',  # NVIDIA Kepler generation CC 3.2
    '3.5': 'KEPLER35',  # NVIDIA Kepler generation CC 3.5
    '3.7': 'KEPLER37',  # NVIDIA Kepler generation CC 3.7
    '5.0': 'MAXWELL50',  # NVIDIA Maxwell generation CC 5.0
    '5.2': 'MAXWELL52',  # NVIDIA Maxwell generation CC 5.2
    '5.3': 'MAXWELL53',  # NVIDIA Maxwell generation CC 5.3
    '6.0': 'PASCAL60',  # NVIDIA Pascal generation CC 6.0
    '6.1': 'PASCAL61',  # NVIDIA Pascal generation CC 6.1
    '7.0': 'VOLTA70',  # NVIDIA Volta generation CC 7.0
    '7.2': 'VOLTA72',  # NVIDIA Volta generation CC 7.2
    '7.5': 'TURING75',  # NVIDIA Turing generation CC 7.5
    '8.0': 'AMPERE80',  # NVIDIA Ampere generation CC 8.0
    '8.6': 'AMPERE86',  # NVIDIA Ampere generation CC 8.6
    '8.9': 'ADA89',  # NVIDIA Ada Lovelace generation CC 8.9
    '9.0': 'HOPPER90',  # NVIDIA Hopper generation CC 9.0
    '10.0': 'BLACKWELL100',  # NVIDIA Blackwell generation CC 10.0
    '12.0': 'BLACKWELL120',  # NVIDIA Blackwell generation CC 12.0
    'gfx906': 'AMD_GFX906',  # MI50 / MI60
    'gfx908': 'AMD_GFX908',  # MI100
    'gfx90a': 'AMD_GFX90A',  # MI200 series
    'gfx940': 'AMD_GFX940',  # MI300 (pre-production)
    'gfx942': 'AMD_GFX942',  # MI300A / MI300X (non-APU)
    'gfx1030': 'AMD_GFX1030',  # V620, W6800
    'gfx1100': 'AMD_GFX1100',  # 7900XT
    'gfx1103': 'AMD_GFX1103',  # Ryzen 8000G, Phoenix series APU
}


_log = fancylogger.getLogger('easyblocks.kokkos')


class EB_Kokkos(CMakeMake):
    """
    Support for building and installing Kokkos
    """

    @staticmethod
    def extra_options(**kwargs):
        """Custom easyconfig parameters for Kokkos"""
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            'kokkos_arch': [None, "Set Kokkos processor arch manually, if auto-detection doesn't work.", CUSTOM],
            'enable_sycl': [False, 'Enable SYCL backend for Intel compilers (default = False)', CUSTOM],
            'enable_multiple_cmake_languages':
                [False, 'Make Kokkos installation usable in CXX and backend-compatible languages.', CUSTOM]
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Kokkos easyblock constructor: determine whether we should build with CUDA support enabled."""
        super().__init__(*args, **kwargs)
        if self.version < LooseVersion('4.1'):
            raise EasyBuildError("Building Kokkos with a version < 4.1 is not supported by this EasyBlock")

        cuda_dep = 'cuda' in [dep['name'].lower() for dep in self.cfg.dependencies(runtime_only=True)]
        cuda_toolchain = hasattr(self.toolchain, 'COMPILER_CUDA_FAMILY')
        self.cuda = cuda_dep or cuda_toolchain

        hip_dep = 'hip' in [dep['name'].lower() for dep in self.cfg.dependencies(runtime_only=True)]
        self.hip = hip_dep

        sycl_dep = 'adaptivecpp' in [dep['name'].lower() for dep in self.cfg.dependencies(runtime_only=True)]
        sycl_toolchain = self.toolchain.comp_family() == toolchain.INTELCOMP and self.cfg['enable_sycl']
        self.sycl = sycl_dep or sycl_toolchain

    def get_kokkos_arch(self, cuda_cc, amdgcn_cc, kokkos_arch):
        """
        Return Kokkos arch based on the Kokkos arch parameter, a generic value, or
        native if neither kokkos_arch nor optarch=GENERIC is set.
        """
        # CPU arch
        # NOTE: if the CPU KOKKOS_ARCH flag is specified, Kokkos will add the correspondent `-march` and `-mtune` flags
        # to the compiler flags, which may override the ones set by EasyBuild.
        # https://github.com/kokkos/kokkos/blob/1a3ea28f6e97b4c9dd2c8ceed53ad58ed5f94dfe/cmake/kokkos_arch.cmake#L228
        processor_arch = None
        if kokkos_arch:
            # If someone is trying a manual override for this case, let them
            if kokkos_arch not in KOKKOS_CPU_ARCH_LIST:
                warning_msg = "Specified CPU ARCH (%s) " % kokkos_arch
                warning_msg += "was not found in listed options [%s]." % KOKKOS_CPU_ARCH_LIST
                warning_msg += "Still might work though."
                print_warning(warning_msg)
            processor_arch = kokkos_arch
        elif build_option('optarch') == OPTARCH_GENERIC:
            # For generic Arm builds we use an existing target;
            # this ensures that KOKKOS_ARCH_ARM_NEON is enabled (Neon is required for armv8-a).
            # For other architectures we set a custom/non-existent type, which will disable all optimizations,
            # and it should use the compiler (optimization) flags set by EasyBuild for this architecture.
            if get_cpu_architecture() == AARCH64:
                processor_arch = 'ARMV80'
            else:
                processor_arch = 'EASYBUILD_GENERIC'
            _log.info("Generic build requested, setting CPU ARCH to %s." % processor_arch)
        # If kokkos_arch was not set...
        else:
            # If we specify a CPU arch, Kokkos' CMake will add the correspondent -march and -mtune flags to the
            # compilation line, possibly overriding the ones set by EasyBuild.
            processor_arch = 'NATIVE'

        # GPU arch
        gpu_arch = None
        if self.cuda:
            # CUDA:
            for cc in sorted(cuda_cc, reverse=True):
                gpu_arch = KOKKOS_GPU_ARCH_TABLE.get(str(cc))
                if gpu_arch:
                    print_warning(
                        "Kokkos will be built _only_ for the latest CUDA compute capability: "
                        "%s" % gpu_arch
                    )
                    break
                else:
                    warning_msg = "(%s) NVIDIA GPU ARCH was not found in listed options." % cc
                    print_warning(warning_msg)

            if not gpu_arch:
                error_msg = "Specified NVIDIA GPU ARCH (%s) " % cuda_cc
                error_msg += "was not found in listed options [%s]." % KOKKOS_GPU_ARCH_TABLE
                raise EasyBuildError(error_msg)

        if gpu_arch is None and self.hip:
            # AMDGPU:
            for cc in sorted(amdgcn_cc, reverse=True):
                gpu_arch = KOKKOS_GPU_ARCH_TABLE.get(str(cc))
                if gpu_arch:
                    print_warning(
                        "Kokkos will be built _only_ for the latest AMDGPU capability: "
                        "%s" % gpu_arch
                    )
                    break
                else:
                    warning_msg = "(%s) AMDGPU ARCH was not found in listed options." % cc
                    print_warning(warning_msg)

            if not gpu_arch:
                error_msg = "Specified AMDGPU ARCH (%s) " % amdgcn_cc
                error_msg += "was not found in listed options [%s]." % KOKKOS_GPU_ARCH_TABLE
                raise EasyBuildError(error_msg)

        return processor_arch, gpu_arch

    def configure_step(self, srcdir=None, builddir=None):
        # Determine GPU arch for CUDA / HIP
        cuda_cc = self.cfg.get_cuda_cc_template_value("cuda_cc_space_sep", required=False).split()
        amdgcn_cc = self.cfg.get_amdgcn_cc_template_value("amdgcn_cc_space_sep", required=False).split()
        processor_arch, gpu_arch = self.get_kokkos_arch(cuda_cc, amdgcn_cc, self.cfg['kokkos_arch'])

        # Set the host architecture
        self.cfg.update('configopts', '-DKokkos_ARCH_%s=ON' % processor_arch)

        # Set the host backend. Serial is not really worthwhile on HPC systems
        if self.toolchain.options.get('openmp', None):
            self.cfg.update('configopts', '-DKokkos_ENABLE_OPENMP=ON')
        else:
            self.cfg.update('configopts', '-DKokkos_ENABLE_THREADS=ON')

        # Set the GPU backend
        if self.cuda and gpu_arch:
            self.cfg.update('configopts', '-DKokkos_ENABLE_CUDA=ON')
            self.cfg.update('configopts', '-DKokkos_ARCH_%s=ON' % gpu_arch)
            self.cfg.update('configopts', '-DKokkos_CUDA_DIR=%s' % get_software_root('CUDA'))
        elif self.hip and gpu_arch:
            self.cfg.update('configopts', '-DKokkos_ENABLE_HIP=ON')
            self.cfg.update('configopts', '-DKokkos_ARCH_%s=ON' % gpu_arch)
            if 'rocthrust' in [dep['name'].lower() for dep in self.cfg.dependencies(runtime_only=True)]:
                self.cfg.update('configopts', '-DKokkos_ENABLE_ROCTRUST=ON')
            else:
                self.cfg.update('configopts', '-DKokkos_ENABLE_ROCTRUST=OFF')
        elif self.sycl:
            self.cfg.update('configopts', '-DKokkos_ENABLE_SYCL=ON')
            if 'onedpl' in [dep['name'].lower() for dep in self.cfg.dependencies(runtime_only=True)]:
                self.cfg.update('configopts', '-DKokkos_ENABLE_ONEDPL=ON')
            else:
                self.cfg.update('configopts', '-DKokkos_ENABLE_ONEDPL=OFF')

        # Enable optional hwloc library if specified in runtime dependencies
        if 'hwloc' in [dep['name'].lower() for dep in self.cfg.dependencies(runtime_only=True)]:
            self.cfg.update('configopts', '-DKokkos_ENABLE_HWLOC=ON')
            self.cfg.update('configopts', '-DKokkos_HWLOC_DIR=%s' % get_software_root('hwloc'))

        # Enable bindings for tuning tools
        self.cfg.update('configopts', '-DKokkos_ENABLE_TUNING=ON')

        if self.cfg['enable_multiple_cmake_languages']:
            if LooseVersion(self.version) < LooseVersion('5.0'):
                raise EasyBuildError('Option enable_multiple_cmake_languages is supported for Kokkos 5.0 and newer.')
            else:
                self.cfg.update('configopts', '-DKokkos_ENABLE_MULTIPLE_CMAKE_LANGUAGES=ON')

        return super().configure_step(srcdir, builddir)
