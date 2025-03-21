# -*- coding: utf-8 -*-
##
# Copyright 2009-2025 Ghent University
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
@author: Kenneth Hoste (Ghent University)
@author: Alan O'Cais (Juelich Supercomputing Centre)
@author: Arkadiy Davydov (University of Warwick)
"""

import glob
import os
import re
import tempfile
import copy
from easybuild.tools import LooseVersion

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.base import fancylogger
from easybuild.framework.easyconfig import CUSTOM, MANDATORY
from easybuild.tools.build_log import EasyBuildError, print_warning, print_msg
from easybuild.tools.config import build_option
from easybuild.tools.filetools import copy_dir, mkdir
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import AARCH64, get_cpu_architecture, get_shared_lib_ext
from easybuild.tools.toolchain.compiler import OPTARCH_GENERIC

from easybuild.easyblocks.generic.cmakemake import CMakeMake

INTEL_PACKAGE_ARCH_LIST = [
    'WSM',  # Intel Westmere CPU (SSE 4.2)
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
    'AMDAVX',  # AMD 64-bit x86 CPU (AVX 1)
    'ZEN',  # AMD Zen class CPU (AVX 2)
    'ZEN2',  # AMD Zen2 class CPU (AVX 2)
    'ZEN3',  # AMD Zen3 class CPU (AVX 2)
    'ARMV80',  # ARMv8.0 Compatible CPU
    'ARMV81',  # ARMv8.1 Compatible CPU
    'ARMV8_THUNDERX',  # ARMv8 Cavium ThunderX CPU
    'ARMV8_THUNDERX2',  # ARMv8 Cavium ThunderX2 CPU
    'A64FX',  # ARMv8.2 with SVE Support
    'BGQ',  # IBM Blue Gene/Q CPU
    'POWER7',  # IBM POWER7 CPU
    'POWER8',  # IBM POWER8 CPU
    'POWER9',  # IBM POWER9 CPU
    'KEPLER30',  # NVIDIA Kepler generation CC 3.0 GPU
    'KEPLER32',  # NVIDIA Kepler generation CC 3.2 GPU
    'KEPLER35',  # NVIDIA Kepler generation CC 3.5 GPU
    'KEPLER37',  # NVIDIA Kepler generation CC 3.7 GPU
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
    'ADA89',  # NVIDIA Ada Lovelace generation CC 8.9 GPU
    'HOPPER90',  # NVIDIA Hopper generation CC 9.0 GPU
    'VEGA900',  # AMD GPU MI25 GFX900
    'VEGA906',  # AMD GPU MI50/MI60 GFX906
    'VEGA908',  # AMD GPU MI100 GFX908
    'VEGA90A',  # AMD GPU MI200 GFX90A
    'NAVI1030',  # AMD GPU MI200 GFX90A
    'NAVI1100',  # AMD GPU RX7900XTX
    'INTEL_GEN',  # Intel GPUs Gen9+
    'INTEL_DG1',  # Intel Iris XeMAX GPU
    'INTEL_GEN9',  # Intel GPU Gen9
    'INTEL_GEN11',  # Intel GPU Gen11
    'INTEL_GEN12LP',  # Intel GPU Gen12LP
    'INTEL_XEHP',  # Intel GPUs Xe-HP
    'INTEL_PVC',  # Intel GPU Ponte Vecchio
] + INTEL_PACKAGE_ARCH_LIST

KOKKOS_LEGACY_ARCH_MAPPING = {
    'ZEN': 'EPYC',
    'ZEN2': 'EPYC',
    'ZEN3': 'EPYC',
    'POWER8': 'Power8',
    'POWER9': 'Power9',
}

KOKKOS_CPU_MAPPING = {
    'sandybridge': 'SNB',
    'ivybridge': 'SNB',
    'haswell': 'HSW',
    'broadwell': 'BDW',
    'skylake_avx512': 'SKX',
    'cascadelake': 'SKX',
    'icelake': 'SKX',
    'sapphirerapids': 'SKX',
    'knights-landing': 'KNL',
    'zen': 'ZEN',
    'zen2': 'ZEN2',
    'zen3': 'ZEN3',
    'power9le': 'POWER9',
}


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
    '9.0': 'HOPPER90',  # NVIDIA Hopper generation CC 9.0
}

# lammps version, which caused the most changes. This may not be precise, but it does work with existing easyconfigs
ref_version = '29Sep2021'

_log = fancylogger.getLogger('easyblocks.lammps')


def translate_lammps_version(version):
    """Translate the LAMMPS version into something that can be used in a comparison"""
    items = [x for x in re.split('(\\d+)', version) if x]
    if len(items) < 3:
        raise ValueError("Version %s does not have (at least) 3 elements" % version)
    month_map = {
       "JAN": '01',
       "FEB": '02',
       "MAR": '03',
       "APR": '04',
       "MAY": '05',
       "JUN": '06',
       "JUL": '07',
       "AUG": '08',
       "SEP": '09',
       "OCT": '10',
       "NOV": '11',
       "DEC": '12'
    }
    return '.'.join([items[2], month_map[items[1].upper()], '%02d' % int(items[0])])


class EB_LAMMPS(CMakeMake):
    """
    Support for building and installing LAMMPS
    """

    def __init__(self, *args, **kwargs):
        """LAMMPS easyblock constructor: determine whether we should build with CUDA support enabled."""
        super(EB_LAMMPS, self).__init__(*args, **kwargs)

        cuda_dep = 'cuda' in [dep['name'].lower() for dep in self.cfg.dependencies()]
        cuda_toolchain = hasattr(self.toolchain, 'COMPILER_CUDA_FAMILY')
        self.cuda = cuda_dep or cuda_toolchain

        # version 1.3.2 is used in the test suite to check easyblock can be initialised
        if self.version != '1.3.2':
            self.cur_version = translate_lammps_version(self.version)
        else:
            self.cur_version = self.version
        self.ref_version = translate_lammps_version(ref_version)

        self.pkg_prefix = 'PKG_'
        if LooseVersion(self.cur_version) >= LooseVersion(self.ref_version):
            self.pkg_user_prefix = self.pkg_prefix
        else:
            self.pkg_user_prefix = self.pkg_prefix + 'USER-'

        if LooseVersion(self.cur_version) >= LooseVersion(self.ref_version):
            self.kokkos_prefix = 'Kokkos'
        else:
            self.kokkos_prefix = 'KOKKOS'
            for cc in KOKKOS_GPU_ARCH_TABLE.keys():
                KOKKOS_GPU_ARCH_TABLE[cc] = KOKKOS_GPU_ARCH_TABLE[cc].lower().title()

        self.kokkos_cpu_mapping = copy.deepcopy(KOKKOS_CPU_MAPPING)
        self.update_kokkos_cpu_mapping()

    @staticmethod
    def extra_options(**kwargs):
        """Custom easyconfig parameters for LAMMPS"""
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            'general_packages': [None, "List of general packages (without prefix PKG_).", MANDATORY],
            'kokkos': [True, "Enable kokkos build.", CUSTOM],
            'kokkos_arch': [None, "Set kokkos processor arch manually, if auto-detection doesn't work.", CUSTOM],
            'user_packages': [None, "List user packages (without prefix PKG_ or USER-PKG_).", CUSTOM],
            'sanity_check_test_inputs': [None, "List of tests for sanity-check.", CUSTOM],
        })
        extra_vars['separate_build_dir'][0] = True
        return extra_vars

    def update_kokkos_cpu_mapping(self):

        if LooseVersion(self.cur_version) >= LooseVersion(translate_lammps_version('31Mar2017')):
            self.kokkos_cpu_mapping['neoverse_n1'] = 'ARMV81'
            self.kokkos_cpu_mapping['neoverse_v1'] = 'ARMV81'

        if LooseVersion(self.cur_version) >= LooseVersion(translate_lammps_version('21sep2021')):
            self.kokkos_cpu_mapping['a64fx'] = 'A64FX'
            self.kokkos_cpu_mapping['zen4'] = 'ZEN3'

        if LooseVersion(self.cur_version) >= LooseVersion(translate_lammps_version('2Aug2023')):
            self.kokkos_cpu_mapping['icelake'] = 'ICX'
            self.kokkos_cpu_mapping['sapphirerapids'] = 'SPR'

    def prepare_step(self, *args, **kwargs):
        """Custom prepare step for LAMMPS."""
        super(EB_LAMMPS, self).prepare_step(*args, **kwargs)

        # Unset LIBS when using both KOKKOS and CUDA - it will mix lib paths otherwise
        if self.cfg['kokkos'] and self.cuda:
            env.unset_env_vars(['LIBS'])

    def configure_step(self, **kwargs):
        """Custom configuration procedure for LAMMPS."""

        if not get_software_root('VTK'):
            if self.cfg['user_packages']:
                self.cfg['user_packages'] = [x for x in self.cfg['user_packages'] if x != 'VTK']
            # In "recent versions" of LAMMPS there is no distinction
            self.cfg['general_packages'] = [x for x in self.cfg['general_packages'] if x != 'VTK']
        if not get_software_root('ScaFaCoS'):
            if self.cfg['user_packages']:
                self.cfg['user_packages'] = [x for x in self.cfg['user_packages'] if x != 'SCAFACOS']
            # In "recent versions" of LAMMPS there is no distinction
            self.cfg['general_packages'] = [x for x in self.cfg['general_packages'] if x != 'SCAFACOS']

        # list of CUDA compute capabilities to use can be specifed in two ways (where (2) overrules (1)):
        # (1) in the easyconfig file, via the custom cuda_compute_capabilities;
        # (2) in the EasyBuild configuration, via --cuda-compute-capabilities configuration option;
        ec_cuda_cc = self.cfg['cuda_compute_capabilities']
        cfg_cuda_cc = build_option('cuda_compute_capabilities')
        if cfg_cuda_cc and not isinstance(cfg_cuda_cc, list):
            raise EasyBuildError("cuda_compute_capabilities in easyconfig should be provided as list of strings, " +
                                 "(for example ['8.0', '7.5']). Got %s" % cfg_cuda_cc)
        cuda_cc = check_cuda_compute_capabilities(cfg_cuda_cc, ec_cuda_cc, cuda=self.cuda)

        # cmake has its own folder
        self.cfg['srcdir'] = os.path.join(self.start_dir, 'cmake')

        # Enable following packages, if not configured in easyconfig
        if LooseVersion(self.cur_version) >= LooseVersion(self.ref_version):
            default_options = ['BUILD_TOOLS']
        else:
            default_options = ['BUILD_DOC', 'BUILD_EXE', 'BUILD_LIB', 'BUILD_TOOLS']

        for option in default_options:
            if "-D%s=" % option not in self.cfg['configopts']:
                self.cfg.update('configopts', '-D%s=on' % option)

        # don't build docs by default (as they use a venv and pull in deps)
        if "-DBUILD_DOC=" not in self.cfg['configopts']:
            self.cfg.update('configopts', '-DBUILD_DOC=off')

        # enable building of shared libraries, if not specified already via configopts
        if self.cfg['build_shared_libs'] is None and '-DBUILD_SHARED_LIBS=' not in self.cfg['configopts']:
            self.cfg['build_shared_libs'] = True

        # Enable gzip, libpng and libjpeg-turbo support when its included as dependency
        deps = [
            ('gzip', 'GZIP'),
            ('libpng', 'PNG'),
            ('libjpeg-turbo', 'JPEG'),
        ]
        for dep_name, with_name in deps:
            with_opt = '-DWITH_%s=' % with_name
            if with_opt not in self.cfg['configopts']:
                if get_software_root(dep_name):
                    self.cfg.update('configopts', with_opt + 'yes')
                else:
                    self.cfg.update('configopts', with_opt + 'no')

        if get_software_root('MDI'):
            # Disable auto-downloading/building MDI dependency:
            if '-DDOWNLOAD_MDI_DEFAULT=' not in self.cfg['configopts']:
                self.cfg.update('configopts', '-DDOWNLOAD_MDI_DEFAULT=OFF')

        # Disable auto-downloading/building Eigen dependency:
        if '-DDOWNLOAD_EIGEN3=' not in self.cfg['configopts']:
            self.cfg.update('configopts', '-DDOWNLOAD_EIGEN3=no')

        # Compiler complains about 'Eigen3_DIR' not being set, but actually it needs 'EIGEN3_INCLUDE_DIR'.
        # see: https://github.com/lammps/lammps/issues/1110
        # Enable Eigen when its included as dependency dependency:
        eigen_root = get_software_root('Eigen')
        if eigen_root:
            if '-DEIGEN3_INCLUDE_DIR=' not in self.cfg['configopts']:
                self.cfg.update('configopts', '-DEIGEN3_INCLUDE_DIR=%s/include/Eigen' % get_software_root('Eigen'))
            if '-DEigen3_DIR=' not in self.cfg['configopts']:
                self.cfg.update('configopts', '-DEigen3_DIR=%s/share/eigen3/cmake/' % get_software_root('Eigen'))

        # LAMMPS Configuration Options
        # https://github.com/lammps/lammps/blob/master/cmake/README.md#lammps-configuration-options
        if self.cfg['general_packages']:
            for package in self.cfg['general_packages']:
                self.cfg.update('configopts', '-D%s%s=on' % (self.pkg_prefix, package))

        if self.cfg['user_packages']:
            for package in self.cfg['user_packages']:
                self.cfg.update('configopts', '-D%s%s=on' % (self.pkg_user_prefix, package))

        # Optimization settings
        pkg_opt = '-D%sOPT=' % self.pkg_prefix
        if pkg_opt not in self.cfg['configopts']:
            self.cfg.update('configopts', pkg_opt + 'on')

        # grab the architecture so we can check if we have Intel hardware (also used for Kokkos below)
        processor_arch, gpu_arch = get_kokkos_arch(self.kokkos_cpu_mapping,
                                                   cuda_cc,
                                                   self.cfg['kokkos_arch'],
                                                   cuda=self.cuda)
        # arch names changed between some releases :(
        if LooseVersion(self.cur_version) < LooseVersion(self.ref_version):
            if processor_arch in KOKKOS_LEGACY_ARCH_MAPPING.keys():
                processor_arch = KOKKOS_LEGACY_ARCH_MAPPING[processor_arch]
            if gpu_arch in KOKKOS_GPU_ARCH_TABLE.values():
                gpu_arch = gpu_arch.capitalize()

        if processor_arch in INTEL_PACKAGE_ARCH_LIST:
            # USER-INTEL enables optimizations on Intel processors. GCC has also partial support for some of them.
            pkg_user_intel = '-D%sINTEL=' % self.pkg_user_prefix
            if pkg_user_intel not in self.cfg['configopts']:
                if self.toolchain.comp_family() in [toolchain.GCC, toolchain.INTELCOMP]:
                    self.cfg.update('configopts', pkg_user_intel + 'on')

        # MPI/OpenMP
        if self.toolchain.options.get('usempi', None):
            self.cfg.update('configopts', '-DBUILD_MPI=yes')
        if self.toolchain.options.get('openmp', None):
            self.cfg.update('configopts', '-DBUILD_OMP=yes')
            if LooseVersion(self.cur_version) >= LooseVersion(self.ref_version):
                self.cfg.update('configopts', '-D%sOPENMP=on' % self.pkg_user_prefix)
            else:
                self.cfg.update('configopts', '-D%sOMP=on' % self.pkg_user_prefix)

        # FFTW
        if get_software_root("imkl") or get_software_root("FFTW"):
            if '-DFFT=' not in self.cfg['configopts']:
                if get_software_root("imkl"):
                    self.log.info("Using the MKL")
                    self.cfg.update('configopts', '-DFFT=MKL')
                else:
                    self.log.info("Using FFTW")
                    self.cfg.update('configopts', '-DFFT=FFTW3')
            if '-DFFT_PACK=' not in self.cfg['configopts']:
                self.cfg.update('configopts', '-DFFT_PACK=array')

        # https://lammps.sandia.gov/doc/Build_extras.html
        # KOKKOS
        if self.cfg['kokkos']:
            print_msg("Using Kokkos package with arch: CPU - %s, GPU - %s" % (processor_arch, gpu_arch))
            self.cfg.update('configopts', '-D%sKOKKOS=on' % self.pkg_prefix)

            if self.toolchain.options.get('openmp', None):
                self.cfg.update('configopts', '-D%s_ENABLE_OPENMP=yes' % self.kokkos_prefix)

            # if KOKKOS and CUDA
            if self.cuda:
                nvcc_wrapper_path = os.path.join(self.start_dir, "lib", "kokkos", "bin", "nvcc_wrapper")
                self.cfg.update('configopts', '-D%s_ENABLE_CUDA=yes' % self.kokkos_prefix)
                if LooseVersion(self.cur_version) >= LooseVersion(self.ref_version):
                    self.cfg.update('configopts', '-D%s_ARCH_%s=yes' % (self.kokkos_prefix, processor_arch))
                    self.cfg.update('configopts', '-D%s_ARCH_%s=yes' % (self.kokkos_prefix, gpu_arch))
                else:
                    # Older versions of Kokkos required us to tweak the C++ compiler
                    self.cfg.update('configopts', '-DCMAKE_CXX_COMPILER="%s"' % nvcc_wrapper_path)
                    self.cfg.update('configopts', '-DCMAKE_CXX_FLAGS="-ccbin $CXX $CXXFLAGS"')
                    self.cfg.update('configopts', '-D%s_ARCH="%s;%s"' % (self.kokkos_prefix, processor_arch, gpu_arch))
            else:
                if LooseVersion(self.cur_version) >= LooseVersion(self.ref_version):
                    self.cfg.update('configopts', '-D%s_ARCH_%s=yes' % (self.kokkos_prefix, processor_arch))
                else:
                    self.cfg.update('configopts', '-D%s_ARCH="%s"' % (self.kokkos_prefix, processor_arch))

        # CUDA only
        elif self.cuda:
            print_msg("Using GPU package (not Kokkos) with arch: CPU - %s, GPU - %s" % (processor_arch, gpu_arch))
            self.cfg.update('configopts', '-D%sGPU=on' % self.pkg_prefix)
            self.cfg.update('configopts', '-DGPU_API=cuda')
            self.cfg.update('configopts', '-DGPU_ARCH=%s' % get_cuda_gpu_arch(cuda_cc))

        # Make sure that all libraries end up in the same folder (python libs seem to default to lib, everything else
        # to lib64)
        self.cfg.update('configopts', '-DCMAKE_INSTALL_LIBDIR=lib')

        # avoid that pip (ab)uses $HOME/.cache/pip
        # cfr. https://pip.pypa.io/en/stable/reference/pip_install/#caching
        env.setvar('XDG_CACHE_HOME', tempfile.gettempdir())
        self.log.info("Using %s as pip cache directory", os.environ['XDG_CACHE_HOME'])

        # Make sure it uses the Python we want
        python_dir = get_software_root('Python')
        if python_dir:
            # Find the Python .so lib
            cmd = 'python -s -c "import sysconfig; print(sysconfig.get_config_var(\'LDLIBRARY\'))"'
            res = run_shell_cmd(cmd, hidden=True)
            if not res.output:
                raise EasyBuildError("Failed to determine Python .so library: %s", res.output)
            python_lib_path = glob.glob(os.path.join(python_dir, 'lib*', res.output.strip()))[0]
            if not python_lib_path:
                raise EasyBuildError("Could not find path to Python .so library: %s", res.output)
            # and the path to the Python include folder
            cmd = 'python -s -c "import sysconfig; print(sysconfig.get_config_var(\'INCLUDEPY\'))"'
            res = run_shell_cmd(cmd, hidden=True)
            if not res.output:
                raise EasyBuildError("Failed to determine Python include dir: %s", res.output)
            python_include_dir = res.output.strip()

            # Whether you need one or the other of the options below depends on the version of CMake and LAMMPS
            # Rather than figure this out, use both (and one will be ignored)
            self.cfg.update('configopts', '-DPython_EXECUTABLE=%s/bin/python' % python_dir)
            self.cfg.update('configopts', '-DPYTHON_EXECUTABLE=%s/bin/python' % python_dir)

            # Older LAMMPS need more hints to get things right as they use deprecated CMake packages
            self.cfg.update('configopts', '-DPYTHON_LIBRARY=%s' % python_lib_path)
            self.cfg.update('configopts', '-DPYTHON_INCLUDE_DIR=%s' % python_include_dir)
        else:
            raise EasyBuildError("Expected to find a Python dependency as sanity check commands rely on it!")

        return super(EB_LAMMPS, self).configure_step()

    def install_step(self):
        """Install LAMMPS and examples/potentials."""
        super(EB_LAMMPS, self).install_step()
        # Copy over the examples so we can repeat the sanity check
        # (some symlinks may be broken)
        examples_dir = os.path.join(self.start_dir, 'examples')
        copy_dir(examples_dir, os.path.join(self.installdir, 'examples'), symlinks=True)
        potentials_dir = os.path.join(self.start_dir, 'potentials')
        copy_dir(potentials_dir, os.path.join(self.installdir, 'potentials'))
        if LooseVersion(self.cur_version) >= LooseVersion(translate_lammps_version('2Aug2023')):
            # From ver 2Aug2023:
            # "make install in a CMake based installation will no longer install
            # the LAMMPS python module. make install-python can be used for that"
            # https://github.com/lammps/lammps/releases/tag/stable_2Aug2023
            pyshortver = '.'.join(get_software_version('Python').split('.')[:2])
            site_packages = os.path.join(self.installdir, 'lib', 'python%s' % pyshortver, 'site-packages')

            mkdir(site_packages, parents=True)

            self.lammpsdir = os.path.join(self.builddir, '%s-*' % self.name.lower())
            self.python_dir = os.path.join(self.lammpsdir, 'python')

            # The -i flag is added through a patch to the lammps source file python/install.py
            # This patch is necessary because the current lammps only allows
            # the lammps python package to be installed system-wide or in user site-packages
            cmd = 'python %(python_dir)s/install.py -p %(python_dir)s/lammps \
                   -l %(builddir)s/easybuild_obj/liblammps.so \
                   -v %(lammpsdir)s/src/version.h -w %(builddir)s/easybuild_obj -i %(site_packages)s' % {
                'python_dir': self.python_dir,
                'builddir': self.builddir,
                'lammpsdir': self.lammpsdir,
                'site_packages': site_packages,
            }

            run_shell_cmd(cmd)

    def sanity_check_step(self, *args, **kwargs):
        """Run custom sanity checks for LAMMPS files, dirs and commands."""

        # Output files need to go somewhere (and has to work for --module-only as well)
        execution_dir = tempfile.mkdtemp()

        if self.cfg['sanity_check_test_inputs']:
            sanity_check_test_inputs = self.cfg['sanity_check_test_inputs']
        else:
            sanity_check_test_inputs = [
                'atm', 'balance', 'colloid', 'crack', 'dipole', 'friction',
                'hugoniostat', 'indent', 'melt', 'min', 'msst',
                'nemd', 'obstacle', 'pour', 'voronoi',
            ]

        custom_commands = [
            # LAMMPS test - you need to call specific test file on path
            'from lammps import lammps; l=lammps(); l.file("%s")' %
            # Examples are part of the install with paths like (installdir)/examples/filename/in.filename
            os.path.join(self.installdir, "examples", "%s" % check_file, "in.%s" % check_file)
            # And this should be done for every file specified above
            for check_file in sanity_check_test_inputs
        ]

        # mpirun command needs an l.finalize() in the sanity check from LAMMPS 29Sep2021
        if LooseVersion(self.cur_version) >= LooseVersion(translate_lammps_version('29Sep2021')):
            custom_commands = [cmd + '; l.finalize()' for cmd in custom_commands]

        custom_commands = ["""python -s -c '%s'""" % cmd for cmd in custom_commands]

        # Execute sanity check commands within an initialized MPI in MPI enabled toolchains
        if self.toolchain.options.get('usempi', None):
            custom_commands = [self.toolchain.mpi_cmd_for(cmd, 1) for cmd in custom_commands]

        # Requires liblammps.so to be findable by the runtime linker (which it might not be if using
        # rpath and filtering out LD_LIBRARY_PATH)
        set_ld_library_path = ''
        if self.installdir not in os.getenv('LD_LIBRARY_PATH', default=''):
            # Use LIBRARY_PATH to set it
            set_ld_library_path = "LD_LIBRARY_PATH=$LIBRARY_PATH:$LD_LIBRARY_PATH "
        custom_commands = ["cd %s && " % execution_dir + set_ld_library_path + cmd for cmd in custom_commands]

        shlib_ext = get_shared_lib_ext()
        custom_paths = {
            'files': [
                os.path.join('bin', 'lmp'),
                os.path.join('include', 'lammps', 'library.h'),
                os.path.join('lib', 'liblammps.%s' % shlib_ext),
            ],
            'dirs': [],
        }

        python = get_software_version('Python')
        if python:
            pyshortver = '.'.join(get_software_version('Python').split('.')[:2])
            pythonpath = os.path.join('lib', 'python%s' % pyshortver, 'site-packages')
            custom_paths['dirs'].append(pythonpath)

        return super(EB_LAMMPS, self).sanity_check_step(custom_commands=custom_commands, custom_paths=custom_paths)


def get_cuda_gpu_arch(cuda_cc):
    """Return CUDA gpu ARCH in LAMMPS required format. Example: 'sm_32' """
    # Get largest cuda supported
    return 'sm_%s' % str(sorted(cuda_cc, reverse=True)[0]).replace(".", "")


def get_kokkos_arch(kokkos_cpu_mapping, cuda_cc, kokkos_arch, cuda=None):
    """
    Return KOKKOS ARCH in LAMMPS required format, which is 'CPU_ARCH' and 'GPU_ARCH'.

    see: https://docs.lammps.org/Build_extras.html#kokkos
    """
    if cuda is None or not isinstance(cuda, bool):
        cuda = get_software_root('CUDA')

    processor_arch = None

    if build_option('optarch') == OPTARCH_GENERIC:
        # For generic Arm builds we use an existing target;
        # this ensures that KOKKOS_ARCH_ARM_NEON is enabled (Neon is required for armv8-a).
        # For other architectures we set a custom/non-existent type, which will disable all optimizations,
        # and it should use the compiler (optimization) flags set by EasyBuild for this architecture.
        if get_cpu_architecture() == AARCH64:
            processor_arch = 'ARMV80'
        else:
            processor_arch = 'EASYBUILD_GENERIC'

        _log.info("Generic build requested, setting CPU ARCH to %s." % processor_arch)
        if kokkos_arch:
            msg = "The specified kokkos_arch (%s) will be ignored " % kokkos_arch
            msg += "because a generic build was requested (via --optarch=GENERIC)"
            print_warning(msg)
    elif kokkos_arch:
        if kokkos_arch not in KOKKOS_CPU_ARCH_LIST:
            warning_msg = "Specified CPU ARCH (%s) " % kokkos_arch
            warning_msg += "was not found in listed options [%s]." % KOKKOS_CPU_ARCH_LIST
            warning_msg += "Still might work though."
            print_warning(warning_msg)
        processor_arch = kokkos_arch

    else:
        warning_msg = "kokkos_arch not set. Trying to auto-detect CPU arch."
        print_warning(warning_msg)

        processor_arch = kokkos_cpu_mapping.get(get_cpu_arch())

        if not processor_arch:
            error_msg = "Couldn't determine CPU architecture, you need to set 'kokkos_arch' manually."
            raise EasyBuildError(error_msg)

        print_msg("Determined cpu arch: %s" % processor_arch)

    gpu_arch = None
    if cuda:
        # CUDA below
        for cc in sorted(cuda_cc, reverse=True):
            gpu_arch = KOKKOS_GPU_ARCH_TABLE.get(str(cc))
            if gpu_arch:
                print_warning(
                    "LAMMPS will be built _only_ for the latest CUDA compute capability known to Kokkos: "
                    "%s" % gpu_arch
                )
                break
            else:
                warning_msg = "(%s) GPU ARCH was not found in listed options." % cc
                print_warning(warning_msg)

        if not gpu_arch:
            error_msg = "Specified GPU ARCH (%s) " % cuda_cc
            error_msg += "was not found in listed options [%s]." % KOKKOS_GPU_ARCH_TABLE
            raise EasyBuildError(error_msg)

    return processor_arch, gpu_arch


def check_cuda_compute_capabilities(cfg_cuda_cc, ec_cuda_cc, cuda=None):
    """
    Checks if cuda-compute-capabilities is set and prints warning if it gets declared on multiple places.

    :param cfg_cuda_cc: cuda-compute-capabilities from cli config
    :param ec_cuda_cc: cuda-compute-capabilities from easyconfig
    :param cuda: boolean to check if cuda should be enabled or not
    :return: returns preferred cuda-compute-capabilities
    """

    if cuda is None or not isinstance(cuda, bool):
        cuda = get_software_root('CUDA')

    cuda_cc = cfg_cuda_cc or ec_cuda_cc or []

    if cuda:
        if cfg_cuda_cc and ec_cuda_cc:
            warning_msg = "cuda_compute_capabilities specified in easyconfig (%s)" % ec_cuda_cc
            warning_msg += " are overruled by "
            warning_msg += "--cuda-compute-capabilities configuration option (%s)" % cfg_cuda_cc
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


def get_cpu_arch():
    """
    Checks for CPU architecture via archspec library.
    https://github.com/archspec/archspec
    Archspec should be bundled as build-dependency to determine CPU arch.
    It can't be called directly in code because it gets available only after prepare_step.

    :return: returns detected cpu architecture
    """
    res = run_shell_cmd("python -s -c 'from archspec.cpu import host; print(host())'")
    if res.exit_code:
        raise EasyBuildError("Failed to determine CPU architecture: %s", res.output)
    return res.output.strip()
