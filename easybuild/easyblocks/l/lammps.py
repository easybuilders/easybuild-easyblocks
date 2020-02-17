##
# Copyright 2009-2020 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# the Hercules foundation (http://www.herculesstichting.be/in_English)
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
@author: Pavel Grochal (INUITS)
"""

import glob
import os
import shutil
import sys

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.framework.easyconfig import CUSTOM, MANDATORY
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


KOKKOS_CPU_ARCH_LIST = [
    'ARMv80',  # ARMv8.0 Compatible CPU
    'ARMv81',  # ARMv8.1 Compatible CPU
    'ARMv8-ThunderX',  # ARMv8 Cavium ThunderX CPU
    'BGQ',  # IBM Blue Gene/Q CPUs
    'Power8',  # IBM POWER8 CPUs
    'Power9',  # IBM POWER9 CPUs
    'SNB',  # Intel Sandy/Ivy Bridge CPUs
    'HSW',  # Intel Haswell CPUs
    'BDW',  # Intel Broadwell Xeon E-class CPUs
    'SKX',  # Intel Sky Lake Xeon E-class HPC CPUs (AVX512)
    'KNC',  # Intel Knights Corner Xeon Phi
    'KNL',  # Intel Knights Landing Xeon Phi
]


KOKKOS_GPU_ARCH_TABLE = {
    "3.0": "Kepler30",  # NVIDIA Kepler generation CC 3.0
    "3.2": "Kepler32",  # NVIDIA Kepler generation CC 3.2
    "3.5": "Kepler35",  # NVIDIA Kepler generation CC 3.5
    "3.7": "Kepler37",  # NVIDIA Kepler generation CC 3.7
    "5.0": "Maxwell50",  # NVIDIA Maxwell generation CC 5.0
    "5.2": "Maxwell52",  # NVIDIA Maxwell generation CC 5.2
    "5.3": "Maxwell53",  # NVIDIA Maxwell generation CC 5.3
    "6.0": "Pascal60",  # NVIDIA Pascal generation CC 6.0
    "6.1": "Pascal61",  # NVIDIA Pascal generation CC 6.1
    "7.0": "Volta70",  # NVIDIA Volta generation CC 7.0
    "7.2": "Volta72",  # NVIDIA Volta generation CC 7.2
    "7.5": "Turing75",  # NVIDIA Turing generation CC 7.5
}


class EB_LAMMPS(CMakeMake):
    """
    Support for building and installing LAMMPS
    """

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for LAMMPS"""

        extra_vars = {
            # see https://developer.nvidia.com/cuda-gpus
            'cuda_compute_capabilities': [[], "List of CUDA compute capabilities to build with", CUSTOM],
            'general_packages': [None, "List of general packages without `PKG_` prefix.", MANDATORY],
            'kokkos': [True, "Enable kokkos build. (enabled by default)", CUSTOM],
            'kokkos_arch': [None, "Set kokkos processor arch manually, if auto-detection doesn't work.", CUSTOM],
            'user_packages': [None, "List user packages without `PKG_USER-` prefix.", MANDATORY],
        }
        return CMakeMake.extra_options(extra_vars)

    def configure_step(self):
        """Custom configuration procedure for LAMMPS."""

        cuda = get_software_root('CUDA')
        # list of CUDA compute capabilities to use can be specifed in two ways (where (2) overrules (1)):
        # (1) in the easyconfig file, via the custom cuda_compute_capabilities;
        # (2) in the EasyBuild configuration, via --cuda-compute-capabilities configuration option;
        ec_cuda_cc = self.cfg['cuda_compute_capabilities']
        cfg_cuda_cc = build_option('cuda_compute_capabilities')
        cuda_cc = cfg_cuda_cc or ec_cuda_cc or []

        # cmake has its own folder
        self.cfg['srcdir'] = os.path.join(self.start_dir, 'cmake')

        # verbose CMake
        if '-DCMAKE_VERBOSE_MAKEFILE=' not in self.cfg['configopts']:
            self.cfg.update('configopts', '-DCMAKE_VERBOSE_MAKEFILE=yes')

        # Enable following packages, if not configured in easycofig
        default_options = [
            'BUILD_DOC', 'BUILD_EXE', 'BUILD_LIB',
            'BUILD_SHARED_LIBS', 'BUILD_TOOLS',
        ]
        for option in default_options:
            if "-D%s=" % option not in self.cfg['configopts']:
                self.cfg.update('configopts', '-D%s=on' % option)

        # Is there a gzip
        if '-DWITH_GZIP=' not in self.cfg['configopts']:
            if get_software_root('gzip'):
                self.cfg.update('configopts', '-DWITH_GZIP=yes')
            else:
                self.cfg.update('configopts', '-DWITH_GZIP=no')

        # Is there a libpng
        if '-DWITH_PNG=' not in self.cfg['configopts']:
            if get_software_root('libpng'):
                self.cfg.update('configopts', '-DWITH_PNG=yes')
            else:
                self.cfg.update('configopts', '-DWITH_PNG=no')

        # Is there a libjpeg-turbo
        if '-DWITH_JPEG=' not in self.cfg['configopts']:
            if get_software_root('libjpeg-turbo'):
                self.cfg.update('configopts', '-DWITH_JPEG=yes')
            else:
                self.cfg.update('configopts', '-DWITH_JPEG=no')

        # With Eigen dependency:
        if '-DDOWNLOAD_EIGEN3=' not in self.cfg['configopts']:
            self.cfg.update('configopts', '-DDOWNLOAD_EIGEN3=no')
        # Compiler complains about 'Eigen3_DIR' not beeing set, but acutally it needs
        # 'EIGEN3_INCLUDE_DIR'.
        # see: https://github.com/lammps/lammps/issues/1110
        if '-DEIGEN3_INCLUDE_DIR=' not in self.cfg['configopts']:
            if get_software_root('Eigen'):
                self.cfg.update('configopts', '-DEIGEN3_INCLUDE_DIR=%s/include/Eigen' % get_software_root('Eigen'))

        if '-DEigen3_DIR=' not in self.cfg['configopts']:
            if get_software_root('Eigen'):
                self.cfg.update('configopts', '-DEigen3_DIR=%s/share/eigen3/cmake/' % get_software_root('Eigen'))

        # LAMMPS Configuration Options
        # https://github.com/lammps/lammps/blob/master/cmake/README.md#lammps-configuration-options
        if self.cfg['general_packages']:
            for package in self.cfg['general_packages']:
                self.cfg.update('configopts', '-DPKG_%s=on' % package)

        if self.cfg['user_packages']:
            for package in self.cfg['user_packages']:
                self.cfg.update('configopts', '-DPKG_USER-%s=on' % package)

        # Optimization settings
        if '-DPKG_OPT=' not in self.cfg['configopts']:
            self.cfg.update('configopts', '-DPKG_OPT=on')

        if '-DPKG_USR-INTEL=' not in self.cfg['configopts']:
            self.cfg.update('configopts', '-DPKG_USER-INTEL=on')

        # MPI/OpenMP
        if self.toolchain.options.get('usempi', None):
            self.cfg.update('configopts', '-DBUILD_MPI=yes')
        if self.toolchain.options.get('openmp', None):
            self.cfg.update('configopts', '-DBUILD_OMP=yes')
            self.cfg.update('configopts', '-DPKG_USER-OMP=on')

        # FFT
        if '-DFFT=' not in self.cfg['configopts']:
            self.cfg.update('configopts', '-DFFT=FFTW3')
        if '-DFFT_PACK=' not in self.cfg['configopts']:
            self.cfg.update('configopts', '-DFFT_PACK=array')

        # https://lammps.sandia.gov/doc/Build_extras.html
        # KOKKOS
        if self.cfg['kokkos']:

            if self.toolchain.options.get('openmp', None):
                self.cfg.update('configopts', '-DKOKKOS_ENABLE_OPENMP=yes')

            self.cfg.update('configopts', '-DPKG_KOKKOS=on')
            self.cfg.update('configopts', '-DKOKKOS_ARCH="%s"' % self.get_kokkos_gpu_arch(cuda_cc))

            # if KOKKOS and CUDA
            if cuda:
                self.check_cuda_compute_capabilities(cfg_cuda_cc, ec_cuda_cc, cuda_cc)
                nvcc_wrapper_path = os.path.join(self.start_dir, "lib", "kokkos", "bin", "nvcc_wrapper")
                # nvcc_wrapper can't find OpenMP for some reason, need to specify OpenMP flags.
                # https://software.intel.com/en-us/forums/intel-oneapi-base-toolkit/topic/842470
                self.cfg.update('configopts', '-DOpenMP_CXX_FLAGS="-qopenmp"')
                self.cfg.update('configopts', '-DOpenMP_CXX_LIB_NAMES="libiomp5"')
                self.cfg.update('configopts', '-DOpenMP_libiomp5_LIBRARY=$EBROOTICC/lib/intel64_lin/libiomp5.so')

                self.cfg.update('configopts', '-DKOKKOS_ENABLE_CUDA=yes')
                self.cfg.update('configopts', '-DCMAKE_CXX_COMPILER="%s"' % nvcc_wrapper_path)
                self.cfg.update('configopts', '-DCMAKE_CXX_FLAGS="-ccbin $CXX $CXXFLAGS"')

        # CUDA only
        elif cuda:
            self.cfg.update('configopts', '-DPKG_GPU=on')
            self.cfg.update('configopts', '-DGPU_API=cuda')

            self.check_cuda_compute_capabilities(cfg_cuda_cc, ec_cuda_cc, cuda_cc)
            self.cfg.update('configopts', '-DGPU_ARCH=%s' % self.get_cuda_gpu_arch(cuda_cc))

        return super(EB_LAMMPS, self).configure_step()

    # This might be needed - keep it as reference
    # def build_step(self):
    #     if self.cfg['kokkos'] and get_software_root('CUDA'):
    #         self.cfg.update('prebuildopts', 'export NVCC_WRAPPER_DEFAULT_COMPILER=$MPICXX &&')
    #     return super(EB_LAMMPS, self).build_step()

    def sanity_check_step(self, *args, **kwargs):
        check_files = [
            'atm', 'balance', 'colloid', 'crack', 'dipole', 'friction',
            'hugoniostat', 'indent', 'melt', 'message', 'min', 'msst',
            'nemd', 'obstacle', 'pour', 'voronoi',
        ]

        custom_commands = [
            # LAMMPS test - you need to call specific test file on path
            """python -c 'from lammps import lammps; l=lammps(); l.file("%s")'""" %
            # The path is joined by "build_dir" (start_dir)/examples/filename/in.filename
            os.path.join(self.start_dir, "examples", "%s" % check_file, "in.%s" % check_file)
            # And this should be done for every file specified above
            for check_file in check_files
        ]

        pyshortver = '.'.join(get_software_version('Python').split('.')[:2])
        pythonpath = os.path.join('lib', 'python%s' % pyshortver, 'site-packages')
        shlib_ext = get_shared_lib_ext()
        custom_paths = {
            'files': [
                'bin/lmp',
                'include/lammps/library.h',
                'lib64/liblammps.%s' % shlib_ext,
            ],
            'dirs': [pythonpath],
        }

        return super(EB_LAMMPS, self).sanity_check_step(
            custom_commands=custom_commands,
            custom_paths=custom_paths,
        )

    def make_module_extra(self):
        """Add install path to PYTHONPATH"""

        txt = super(EB_LAMMPS, self).make_module_extra()

        pyshortver = '.'.join(get_software_version('Python').split('.')[:2])
        pythonpath = os.path.join('lib', 'python%s' % pyshortver, 'site-packages')

        txt += self.module_generator.prepend_paths('PYTHONPATH', [pythonpath, "lib64"])
        txt += self.module_generator.prepend_paths('LD_LIBRARY_PATH', ["lib64"])

        return txt

    def get_cuda_gpu_arch(self, cuda_cc):
        cuda_cc.sort(reverse=True)
        return 'sm_%' % str(cuda_cc[0]).replace(".", "")

    def get_kokkos_gpu_arch(self, cuda_cc):
        # see: https://lammps.sandia.gov/doc/Build_extras.html#kokkos
        cuda = get_software_root('CUDA')
        processor_arch = None

        if self.cfg['kokkos_arch']:
            if self.cfg['kokkos_arch'] not in KOKKOS_CPU_ARCH_LIST:
                warning_msg = "Specified CPU ARCH (%s) " % self.cfg['kokkos_arch']
                warning_msg += "was not found in listed options [%s]." % KOKKOS_CPU_ARCH_LIST
                warning_msg += "Still might work though."
                print_warning(warning_msg)
            processor_arch = self.cfg['kokkos_arch']

        else:
            warning_msg = "kokkos_arch not set. Trying to auto-detect CPU arch."
            print_warning(warning_msg)

            cpu_arch = self.get_cpu_arch()

            if cpu_arch == "sandybridge" or cpu_arch == "ivybridge":
                processor_arch = 'SNB'
            elif cpu_arch == "haswell":
                processor_arch = 'HSW'
            elif cpu_arch == "broadwell":
                processor_arch = 'BDW'
            elif cpu_arch == "skylake":
                processor_arch = 'SKX'
            elif cpu_arch == "knights-landing":
                processor_arch = 'KNL'
            else:
                error_msg = "Couldn't determine CPU architecture, you need to set 'kokkos_arch' manually."
                raise EasyBuildError(error_msg)
                exit(1)
            print("Determined cpu arch: %s" % processor_arch)

        if not cuda:
            return processor_arch

        # CUDA below
        cuda_cc.sort(reverse=True)
        gpu_arch = None
        for cc in cuda_cc:
            gpu_arch = KOKKOS_GPU_ARCH_TABLE.get(str(cc))
            if gpu_arch:
                break
            else:
                warning_msg = "(%s) GPU ARCH was not found in listed options." % cc
                print_warning(warning_msg)

        if not gpu_arch:
            error_msg = "Specified GPU ARCH (%s) " % cuda_cc
            error_msg += "was not found in listed options [%s]." % KOKKOS_GPU_ARCH_TABLE
            raise EasyBuildError(error_msg)
        return "%s;%s" % (processor_arch, gpu_arch)

    def check_cuda_compute_capabilities(self, cfg_cuda_cc, ec_cuda_cc, cuda_cc):
        cuda = get_software_root('CUDA')

        if cuda:
            if cfg_cuda_cc and ec_cuda_cc:
                warning_msg = "cuda_compute_capabilities specified in easyconfig (%s)" % self.ec_cuda_cc
                warning_msg += " are overruled by "
                warning_msg += "--cuda-compute-capabilities configuration option (%s)" % self.cfg_cuda_cc
                print_warning(warning_msg)
            elif not cuda_cc:
                error_msg = "No CUDA compute capabilities specified.\nTo build LAMMPS with Cuda you need to use"
                error_msg += "the --cuda-compute-capabilities configuration option or the cuda_compute_capabilities "
                error_msg += "easyconfig parameter to specify a list of CUDA compute capabilities to compile with."
                raise EasyBuildError(error_msg)

        elif cuda_cc:
            warning_msg = "Missing CUDA package (in dependencies), "
            warning_msg += "but 'cuda_compute_capabilities' option was specified."
            print_warning(warning_msg)

        return cuda_cc

    def get_cpu_arch(self):
        out, ec = run_cmd("python -c 'from archspec.cpu import host; print(host())'", simple=False)
        if ec:
            raise EasyBuildError("Failed to determine CPU architecture: %s", out)
        # transform: 'skylake_avx512\n' => 'skylake'
        return out.strip().split("_")[0]
