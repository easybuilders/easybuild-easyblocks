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
EasyBuild support for OpenMPI, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
import os
import re

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.modules import get_software_root
from easybuild.tools.systemtools import check_os_dependency, get_shared_lib_ext


class EB_OpenMPI(ConfigureMake):
    """OpenMPI easyblock."""

    def configure_step(self):
        """Custom configuration step for OpenMPI."""

        def config_opt_unused(key, enable_opt=False):
            """Helper function to check whether a configure option is already specified in 'configopts'."""
            if enable_opt:
                regex = re.compile('--(disable|enable)-%s' % key)
            else:
                regex = re.compile('--(with|without)-%s' % key)

            return not bool(regex.search(self.cfg['configopts']))

        config_opt_names = [
            # suppress failure modes in relation to mpirun path
            'mpirun-prefix-by-default',
            # build shared libraries
            'shared',
        ]

        for key in config_opt_names:
            if config_opt_unused(key, enable_opt=True):
                self.cfg.update('configopts', '--enable-%s' % key)

        # check whether VERBS support should be enabled
        if config_opt_unused('verbs'):

            # auto-detect based on available OS packages
            verbs = False
            for osdep in ['libibverbs-dev', 'libibverbs-devel', 'rdma-core-devel']:
                if check_os_dependency(osdep):
                    verbs = True
                    break

            if verbs:
                self.cfg.update('configopts', '--with-verbs')
            else:
                self.cfg.update('configopts', '--without-verbs')

        # handle dependencies
        for dep in ['CUDA', 'hwloc', 'libevent', 'PMIx', 'UCX']:
            if config_opt_unused(dep.lower()):
                dep_root = get_software_root(dep)
                if dep_root:
                    self.cfg.update('configopts', '--with-%s=%s' % (dep.lower(), dep_root))

        super(EB_OpenMPI, self).configure_step()

    def sanity_check_step(self):
        """Custom sanity check for OpenMPI."""

        bin_names = ['mpicc', 'mpicxx', 'mpif90', 'mpifort', 'mpirun', 'ompi_info', 'opal_wrapper', 'orterun']
        bin_files = [os.path.join('bin', x) for x in bin_names]

        shlib_ext = get_shared_lib_ext()
        lib_names = ['mpi_mpifh', 'mpi', 'ompitrace', 'open-pal', 'open-rte']
        lib_files = [os.path.join('lib', 'lib%s.%s' % (x, shlib_ext)) for x in lib_names]

        inc_names = ['mpi-ext', 'mpif-config', 'mpif', 'mpi', 'mpi_portable_platform']
        inc_files = [os.path.join('include', x + '.h') for x in inc_names]

        custom_paths = {
            'files': bin_files + inc_files + lib_files,
            'dirs': [],
        }

        # make sure MPI compiler wrappers pick up correct compilers
        expected = {
            'mpicc': os.getenv('CC', 'gcc'),
            'mpicxx': os.getenv('CXX', 'g++'),
            'mpifort': os.getenv('FC', 'gfortran'),
            'mpif90': os.getenv('F90', 'gfortran'),
        }
        # actual pattern for gfortran is "GNU Fortran"
        for key in ['mpifort', 'mpif90']:
            if expected[key] == 'gfortran':
                expected[key] = "GNU Fortran"
        # for PGI, correct pattern is "pgfortran" with mpif90
        if expected['mpif90'] == 'pgf90':
            expected['mpif90'] = 'pgfortran'

        custom_commands = ["%s --version | grep '%s'" % (key, expected[key]) for key in sorted(expected.keys())]

        super(EB_OpenMPI, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
