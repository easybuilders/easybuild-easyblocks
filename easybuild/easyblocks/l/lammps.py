# -*- coding: utf-8 -*-
##
# Copyright 2009-2021 Ghent University
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
"""

import os
import tempfile

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.framework.easyconfig import CUSTOM, MANDATORY
from easybuild.tools.build_log import EasyBuildError, print_warning, print_msg
from easybuild.tools.config import build_option
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import X86_64, get_cpu_architecture, get_shared_lib_ext

from easybuild.easyblocks.generic.cmakemake import CMakeMake

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
    'EPYC',  # AMD EPYC Zen-Core CPU
]

KOKKOS_CPU_MAPPING = {
    'sandybridge': 'SNB',
    'ivybridge': 'SNB',
    'haswell': 'HSW',
    'broadwell': 'BDW',
    'skylake_avx512': 'SKX',
    'cascadelake': 'SKX',
    'knights-landing': 'KNL',
    'zen': 'EPYC',
    'zen2': 'EPYC',  # KOKKOS doesn't seem to distinguish between zen and zen2 (yet?)
    'power9le': 'Power9',
}


KOKKOS_GPU_ARCH_TABLE = {
    '3.0': 'Kepler30',  # NVIDIA Kepler generation CC 3.0
    '3.2': 'Kepler32',  # NVIDIA Kepler generation CC 3.2
    '3.5': 'Kepler35',  # NVIDIA Kepler generation CC 3.5
    '3.7': 'Kepler37',  # NVIDIA Kepler generation CC 3.7
    '5.0': 'Maxwell50',  # NVIDIA Maxwell generation CC 5.0
    '5.2': 'Maxwell52',  # NVIDIA Maxwell generation CC 5.2
    '5.3': 'Maxwell53',  # NVIDIA Maxwell generation CC 5.3
    '6.0': 'Pascal60',  # NVIDIA Pascal generation CC 6.0
    '6.1': 'Pascal61',  # NVIDIA Pascal generation CC 6.1
    '7.0': 'Volta70',  # NVIDIA Volta generation CC 7.0
    '7.2': 'Volta72',  # NVIDIA Volta generation CC 7.2
    '7.5': 'Turing75',  # NVIDIA Turing generation CC 7.5
    '8.0': 'AMPERE80',  # NVIDIA Ampere generation CC 8.0
    '8.6': 'AMPERE86',  # NVIDIA Ampere generation CC 8.6
}

PKG_PREFIX = 'PKG_'
PKG_USER_PREFIX = PKG_PREFIX + 'USER-'


class EB_LAMMPS(CMakeMake):
    """
    Support for building and installing LAMMPS
    """

    @staticmethod
    def extra_options(**kwargs):
        """Custom easyconfig parameters for LAMMPS"""
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            'general_packages': [None, "List of general packages without '%s' prefix." % PKG_PREFIX, MANDATORY],
            'kokkos': [True, "Enable kokkos build.", CUSTOM],
            'kokkos_arch': [None, "Set kokkos processor arch manually, if auto-detection doesn't work.", CUSTOM],
            'user_packages': [None, "List user packages without '%s' prefix." % PKG_USER_PREFIX, MANDATORY],
        })
        extra_vars['separate_build_dir'][0] = True
        return extra_vars

    def prepare_step(self, *args, **kwargs):
        """Custom prepare step for LAMMPS."""
        super(EB_LAMMPS, self).prepare_step(*args, **kwargs)

        # Unset LIBS when using both KOKKOS and CUDA - it will mix lib paths otherwise
        if self.cfg['kokkos'] and get_software_root('CUDA'):
            env.unset_env_vars(['LIBS'])

    def configure_step(self, **kwargs):
        """Custom configuration procedure for LAMMPS."""
        if not get_software_root('VTK'):
            self.cfg['user_packages'] = [x for x in self.cfg['user_packages'] if x != 'VTK']
        if not get_software_root('ScaFaCoS'):
            self.cfg['user_packages'] = [x for x in self.cfg['user_packages'] if x != 'SCAFACOS']
        if not get_software_root('yaff'):
            self.cfg['user_packages'] = [x for x in self.cfg['user_packages'] if x != 'YAFF']
            self.cfg['sanity_check_commands'] = [x for x in self.cfg['sanity_check_commands']
                                                 if 'yaff' not in x]

        cuda = get_software_root('CUDA')
        # list of CUDA compute capabilities to use can be specifed in two ways (where (2) overrules (1)):
        # (1) in the easyconfig file, via the custom cuda_compute_capabilities;
        # (2) in the EasyBuild configuration, via --cuda-compute-capabilities configuration option;
        ec_cuda_cc = self.cfg['cuda_compute_capabilities']
        cfg_cuda_cc = build_option('cuda_compute_capabilities')
        cuda_cc = check_cuda_compute_capabilities(cfg_cuda_cc, ec_cuda_cc)

        # cmake has its own folder
        self.cfg['srcdir'] = os.path.join(self.start_dir, 'cmake')

        # Enable following packages, if not configured in easyconfig
        default_options = ['BUILD_DOC', 'BUILD_EXE', 'BUILD_LIB', 'BUILD_TOOLS']
        for option in default_options:
            if "-D%s=" % option not in self.cfg['configopts']:
                self.cfg.update('configopts', '-D%s=on' % option)

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

        # Disable auto-downloading/building Eigen dependency:
        if '-DDOWNLOAD_EIGEN3=' not in self.cfg['configopts']:
            self.cfg.update('configopts', '-DDOWNLOAD_EIGEN3=no')

        # Compiler complains about 'Eigen3_DIR' not beeing set, but acutally it needs 'EIGEN3_INCLUDE_DIR'.
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
                self.cfg.update('configopts', '-D%s%s=on' % (PKG_PREFIX, package))

        if self.cfg['user_packages']:
            for package in self.cfg['user_packages']:
                self.cfg.update('configopts', '-D%s%s=on' % (PKG_USER_PREFIX, package))

        # Optimization settings
        pkg_opt = '-D%sOPT=' % PKG_PREFIX
        if pkg_opt not in self.cfg['configopts']:
            self.cfg.update('configopts', pkg_opt + 'on')

        if get_cpu_architecture() == X86_64:
            # USER-INTEL enables optimizations on Intel processors. GCC has also partial support for some of them.
            pkg_user_intel = '-D%sINTEL=' % PKG_USER_PREFIX
            if pkg_user_intel not in self.cfg['configopts']:
                if self.toolchain.comp_family() in [toolchain.GCC, toolchain.INTELCOMP]:
                    self.cfg.update('configopts', pkg_user_intel + 'on')

        # MPI/OpenMP
        if self.toolchain.options.get('usempi', None):
            self.cfg.update('configopts', '-DBUILD_MPI=yes')
        if self.toolchain.options.get('openmp', None):
            self.cfg.update('configopts', '-DBUILD_OMP=yes')
            self.cfg.update('configopts', '-D%sOMP=on' % PKG_USER_PREFIX)

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

            if self.toolchain.options.get('openmp', None):
                self.cfg.update('configopts', '-DKOKKOS_ENABLE_OPENMP=yes')

            self.cfg.update('configopts', '-D%sKOKKOS=on' % PKG_PREFIX)
            self.cfg.update('configopts', '-DKOKKOS_ARCH="%s"' % get_kokkos_arch(cuda_cc, self.cfg['kokkos_arch']))

            # if KOKKOS and CUDA
            if cuda:
                nvcc_wrapper_path = os.path.join(self.start_dir, "lib", "kokkos", "bin", "nvcc_wrapper")
                self.cfg.update('configopts', '-DKOKKOS_ENABLE_CUDA=yes')
                self.cfg.update('configopts', '-DCMAKE_CXX_COMPILER="%s"' % nvcc_wrapper_path)
                self.cfg.update('configopts', '-DCMAKE_CXX_FLAGS="-ccbin $CXX $CXXFLAGS"')

        # CUDA only
        elif cuda:
            self.cfg.update('configopts', '-D%sGPU=on' % PKG_PREFIX)
            self.cfg.update('configopts', '-DGPU_API=cuda')
            self.cfg.update('configopts', '-DGPU_ARCH=%s' % get_cuda_gpu_arch(cuda_cc))

        # avoid that pip (ab)uses $HOME/.cache/pip
        # cfr. https://pip.pypa.io/en/stable/reference/pip_install/#caching
        env.setvar('XDG_CACHE_HOME', tempfile.gettempdir())
        self.log.info("Using %s as pip cache directory", os.environ['XDG_CACHE_HOME'])

        return super(EB_LAMMPS, self).configure_step()

    def sanity_check_step(self, *args, **kwargs):
        """Run custom sanity checks for LAMMPS files, dirs and commands."""
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

        # Execute sanity check commands within an initialized MPI in MPI enabled toolchains
        if self.toolchain.options.get('usempi', None):
            custom_commands = [self.toolchain.mpi_cmd_for(cmd, 1) for cmd in custom_commands]

        shlib_ext = get_shared_lib_ext()
        custom_paths = {
            'files': [
                os.path.join('bin', 'lmp'),
                os.path.join('include', 'lammps', 'library.h'),
                os.path.join('lib64', 'liblammps.%s' % shlib_ext),
            ],
            'dirs': [],
        }

        python = get_software_version('Python')
        if python:
            pyshortver = '.'.join(get_software_version('Python').split('.')[:2])
            pythonpath = os.path.join('lib', 'python%s' % pyshortver, 'site-packages')
            custom_paths['dirs'].append(pythonpath)

        return super(EB_LAMMPS, self).sanity_check_step(custom_commands=custom_commands, custom_paths=custom_paths)

    def make_module_extra(self):
        """Add install path to PYTHONPATH"""

        txt = super(EB_LAMMPS, self).make_module_extra()

        python = get_software_version('Python')
        if python:
            pyshortver = '.'.join(get_software_version('Python').split('.')[:2])
            pythonpath = os.path.join('lib', 'python%s' % pyshortver, 'site-packages')
            txt += self.module_generator.prepend_paths('PYTHONPATH', [pythonpath])

        return txt


def get_cuda_gpu_arch(cuda_cc):
    """Return CUDA gpu ARCH in LAMMPS required format. Example: 'sm_32' """
    # Get largest cuda supported
    return 'sm_%s' % str(sorted(cuda_cc, reverse=True)[0]).replace(".", "")


def get_kokkos_arch(cuda_cc, kokkos_arch):
    """
    Return KOKKOS ARCH in LAMMPS required format, which is either 'CPU_ARCH' or 'CPU_ARCH;GPU_ARCH'.

    see: https://lammps.sandia.gov/doc/Build_extras.html#kokkos
    """
    cuda = get_software_root('CUDA')
    processor_arch = None

    if kokkos_arch:
        if kokkos_arch not in KOKKOS_CPU_ARCH_LIST:
            warning_msg = "Specified CPU ARCH (%s) " % kokkos_arch
            warning_msg += "was not found in listed options [%s]." % KOKKOS_CPU_ARCH_LIST
            warning_msg += "Still might work though."
            print_warning(warning_msg)
        processor_arch = kokkos_arch

    else:
        warning_msg = "kokkos_arch not set. Trying to auto-detect CPU arch."
        print_warning(warning_msg)

        processor_arch = KOKKOS_CPU_MAPPING.get(get_cpu_arch())

        if not processor_arch:
            error_msg = "Couldn't determine CPU architecture, you need to set 'kokkos_arch' manually."
            raise EasyBuildError(error_msg)

        print_msg("Determined cpu arch: %s" % processor_arch)

    if cuda:
        # CUDA below
        gpu_arch = None
        for cc in sorted(cuda_cc, reverse=True):
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

        kokkos_arch = "%s;%s" % (processor_arch, gpu_arch)

    else:
        kokkos_arch = processor_arch

    return kokkos_arch


def check_cuda_compute_capabilities(cfg_cuda_cc, ec_cuda_cc):
    """
    Checks if cuda-compute-capabilities is set and prints warning if it gets declared on multiple places.

    :param cfg_cuda_cc: cuda-compute-capabilities from cli config
    :param ec_cuda_cc: cuda-compute-capabilities from easyconfig
    :return: returns preferred cuda-compute-capabilities
    """

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
    out, ec = run_cmd("python -c 'from archspec.cpu import host; print(host())'", simple=False)
    if ec:
        raise EasyBuildError("Failed to determine CPU architecture: %s", out)
    return out.strip()
