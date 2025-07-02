##
# Copyright 2009-2025 Ghent University, Forschungszentrum Juelich
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
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
EasyBuild support for building and installing the MPICH MPI library and derivatives, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Damian Alvarez (Forschungszentrum Juelich)
@author: Xavier Besseron (University of Luxembourg)
"""
import os
from easybuild.tools import LooseVersion

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.systemtools import get_shared_lib_ext
from easybuild.tools.modules import get_software_root

DEVICES_WITH_UCX_SUPPORT = ['ch4']


class EB_MPICH(ConfigureMake):
    """
    Support for building the MPICH MPI library and derivatives.
    - basically redefinition of environment variables
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Define custom easyconfig parameters specific to MPICH."""
        extra_vars = ConfigureMake.extra_options(extra_vars)
        extra_vars.update({
            'debug': [False, "Enable debug build (which is slower)", CUSTOM],
            'device': ['ch4', "Device to use for MPICH (e.g. ch4, ch3)", CUSTOM],
            'mpi_abi': [False, "Enable build with MPI ABI compatibility", CUSTOM],
        })
        return extra_vars

    # MPICH configure script complains when F90 or F90FLAGS are set,
    # they should be replaced with FC/FCFLAGS instead.
    # Additionally, there are a set of variables (FCFLAGS among them) that should not be set at configure time,
    # or they will leak in the mpix wrappers.
    # Specific variables to be included in the wrapper exists, but they changed between MPICH 3.1.4 and MPICH 3.2
    # and in a typical scenario we probably don't want them.
    def correct_mpich_build_env(self):
        """
        Method to correctly set the environment for MPICH and derivatives
        """
        env_vars = ['CFLAGS', 'CPPFLAGS', 'CXXFLAGS', 'FCFLAGS', 'FFLAGS', 'LDFLAGS', 'LIBS']
        vars_to_unset = ['F90', 'F90FLAGS']
        vars_to_keep = []
        for envvar in env_vars:
            envvar_val = os.getenv(envvar)
            if envvar_val:
                new_envvar = 'MPICHLIB_%s' % envvar
                new_envvar_val = os.getenv(new_envvar)
                vars_to_unset.append(envvar)
                if envvar_val == new_envvar_val:
                    self.log.debug("$%s == $%s, just defined $%s as empty", envvar, new_envvar, envvar)
                elif new_envvar_val is None:
                    env.setvar(new_envvar, envvar_val)
                else:
                    raise EasyBuildError("Both $%s and $%s set, can I overwrite $%s with $%s (%s) ?",
                                         envvar, new_envvar, new_envvar, envvar, envvar_val)

        # With MPICH 3.4.2-GCCcore-10.3.0 the configure script will fail complaining that `-fallow-argument-mismatch`
        # is not present in the FFLAGS variable.
        version = LooseVersion(self.version)
        if version < LooseVersion('4'):
            self.log.info("MPICH version < 4, not unsetting FFLAGS to avoid configure failure")
            vars_to_keep.append('FFLAGS')

        vars_to_unset = list(set(vars_to_unset) - set(vars_to_keep))

        env.unset_env_vars(vars_to_unset)

    def add_mpich_configopts(self):
        """
        Method to add common configure options for MPICH-based MPI libraries
        """
        # additional configuration options
        add_configopts = []

        if self.cfg['debug']:
            # debug build, with error checking, timing and debug info
            # note: this will affect performance
            if LooseVersion(self.version) < LooseVersion('4.0.0'):
                add_configopts.append('--enable-fast=none')
            else:
                add_configopts.append('--enable-error-checking=all')
                add_configopts.append('--enable-timing=runtime')
                add_configopts.append('--enable-debuginfo')
        else:
            # optimized build, no error checking, timing or debug info
            if LooseVersion(self.version) < LooseVersion('4.0.0'):
                add_configopts.append('--enable-fast')
            else:
                add_configopts.append('--enable-error-checking=no')
                add_configopts.append('--enable-timing=none')

        device = self.cfg['device']

        ucx_root = get_software_root('UCX')
        if ucx_root:
            if ':' in device:
                raise EasyBuildError("Device channel already manually specified in device = '%s'.", device)
            elif device not in DEVICES_WITH_UCX_SUPPORT:
                raise EasyBuildError(
                    "Device '%s' does not support UCX, please use one of %s.",
                    device, ', '.join(DEVICES_WITH_UCX_SUPPORT)
                )
            device += ':ucx'
            add_configopts.append(f'--with-ucx={ucx_root}')
            self.log.info("Enabling UCX support, using UCX root: %s", ucx_root)

        hwloc_root = get_software_root('hwloc')
        if hwloc_root:
            if LooseVersion(self.version) < LooseVersion('4'):
                add_configopts.append(f'--with-hwloc-prefix={hwloc_root}')
            else:
                add_configopts.append(f'--with-hwloc={hwloc_root}')
            self.log.info("Enabling hwloc support, using hwloc root: %s", hwloc_root)
        else:
            add_configopts.append('--without-hwloc')
            self.log.info("hwloc dependency not found, disabling hwloc support")

        if self.cfg['mpi_abi']:
            if LooseVersion(self.version) < LooseVersion('4.3'):
                raise EasyBuildError("MPI ABI compatibility is not supported in MPICH < 4.3")
            self.log.info("Enabling MPI ABI compatibility")
            add_configopts.append('--enable-mpi-abi')

        cuda_root = get_software_root('CUDA')
        if cuda_root:
            self.log.info("CUDA dependency detected, enabling CUDA support")
            if LooseVersion(self.version) < LooseVersion('4'):
                raise EasyBuildError("CUDA support is not available in MPICH < 4.x")
            add_configopts.append(f'--with-cuda={cuda_root}')

        # enable shared libraries, using GCC and GNU ld options
        add_configopts.append('--enable-shared')
        # enable static libraries
        add_configopts.append('--enable-static')
        # enable Fortran 77/90 and C++ bindings
        add_configopts.extend(['--enable-fortran=all', '--enable-cxx'])

        add_configopts.append(f'--with-device={device}')

        self.cfg.update('configopts', ' '.join(add_configopts))

    def configure_step(self, add_mpich_configopts=True):
        """
        Custom configuration procedure for MPICH

        * add common configure options for MPICH-based MPI libraries
        * unset environment variables that leak into mpi* wrappers, and define $MPICHLIB_* equivalents instead
        """

        # things might go wrong if a previous install dir is present, so let's get rid of it
        if not self.cfg['keeppreviousinstall']:
            self.log.info("Making sure any old installation is removed before we start the build...")
            super().make_dir(self.installdir, True, dontcreateinstalldir=True)

        if add_mpich_configopts:
            self.add_mpich_configopts()

        self.correct_mpich_build_env()

        super().configure_step()

    # make and make install are default

    def sanity_check_step(self, custom_paths=None, use_new_libnames=None, check_launchers=True, check_static_libs=True):
        """
        Custom sanity check for MPICH
        """
        shlib_ext = get_shared_lib_ext()
        if custom_paths is None:
            custom_paths = {}

        if use_new_libnames is None:
            # cfr. http://git.mpich.org/mpich.git/blob_plain/v3.1.1:/CHANGES
            # MPICH changed its library names sinceversion 3.1.1
            use_new_libnames = LooseVersion(self.version) >= LooseVersion('3.1.1')

        # Starting MPICH 3.1.1, libraries have been renamed
        # cf http://git.mpich.org/mpich.git/blob_plain/v3.1.1:/CHANGES
        if use_new_libnames:
            libnames = ['mpi', 'mpicxx', 'mpifort']
        else:
            libnames = ['fmpich', 'mpichcxx', 'mpichf90', 'mpich', 'mpl', 'opa']

        binaries = ['mpicc', 'mpicxx', 'mpif77', 'mpif90']
        if check_launchers:
            binaries.extend(['mpiexec', 'mpiexec.hydra', 'mpirun'])

        if self.cfg['mpi_abi']:
            libnames.append('mpi_abi')

        bins = [os.path.join('bin', x) for x in binaries]
        headers = [os.path.join('include', x) for x in ['mpi.h', 'mpicxx.h', 'mpif.h']]
        lib_exts = [shlib_ext]
        if check_static_libs:
            lib_exts.append('a')
        libs_fn = ['lib%s.%s' % (lib, e) for lib in libnames for e in lib_exts]
        libs = [(os.path.join('lib', lib), os.path.join('lib64', lib)) for lib in libs_fn]

        custom_paths.setdefault('dirs', []).extend(['bin', 'include', ('lib', 'lib64')])
        custom_paths.setdefault('files', []).extend(bins + headers + libs)

        super().sanity_check_step(custom_paths=custom_paths)
