##
# Copyright 2016-2018 Ghent University, Forschungszentrum Juelich
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
EasyBuild support for building and installing the ParaStationMPI library, implemented as an easyblock

@author: Damian Alvarez (Forschungszentrum Juelich)
"""

import easybuild.tools.toolchain as toolchain
import os
import re

from distutils.version import LooseVersion
from easybuild.easyblocks.mpich import EB_MPICH
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_msg
from easybuild.tools.filetools import mkdir, remove_dir, write_file
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd


PINGPONG_PGO_TEST = """
/****************************************
 * Buggy, ugly and extremely simple MPI ping pong.
 * The goal is to trigger pscom internal routines
 * to generate profiles to be used by PGO-enabled
 * compilers.
 *
 * Nothing more, nothing less.
 *
 * We try small and large messages to walk the path for
 * eager and rendezvous protocols
 ****************************************/

#include "mpi.h"
#define MAX_LENGTH 1048576

int main(int argc, char *argv[]){
    int myid, vlength;

    double v0[MAX_LENGTH], v1[MAX_LENGTH];

    MPI_Status stat;

    MPI_Init(&argc,&argv);

    MPI_Comm_rank(MPI_COMM_WORLD, &myid);

    for (vlength=1; vlength<=MAX_LENGTH; vlength*=2){
        MPI_Barrier(MPI_COMM_WORLD);

        if (myid == 0){
            MPI_Send(v0, vlength, MPI_DOUBLE, 1, 0, MPI_COMM_WORLD);
            MPI_Recv(v1, vlength, MPI_DOUBLE, 1, 0, MPI_COMM_WORLD, &stat);
        }
        else{
            MPI_Recv(v1, vlength, MPI_DOUBLE, 0, 0, MPI_COMM_WORLD, &stat);
            MPI_Send(v0, vlength, MPI_DOUBLE, 0, 0, MPI_COMM_WORLD);
        }
    }
    MPI_Finalize();
}
"""


class EB_psmpi(EB_MPICH):
    """
    Support for building the ParaStationMPI library.
    * Determines the compiler to be used based on the toolchain
    * Enables threading if required by the easyconfig
    * Sets extra MPICH options if required by the easyconfig
    """

    def __init__(self, *args, **kwargs):
        super(EB_psmpi, self).__init__(*args, **kwargs)
        self.prof_dir = os.path.join(self.builddir, 'profile')

    @staticmethod
    def extra_options(extra_vars=None):
        """Define custom easyconfig parameters specific to ParaStationMPI."""
        extra_vars = EB_MPICH.extra_options(extra_vars)

        # ParaStationMPI doesn't offer this build option, and forcing it in the MPICH build
        # can be potentially conflictive with other options set by psmpi configure script.
        del extra_vars['debug']

        extra_vars.update({
            'mpich_opts': [None, "Optional options to configure MPICH", CUSTOM],
            'threaded': [False, "Enable multithreaded build (which is slower)", CUSTOM],
            'pscom_allin_path': [None, "Enable pscom integration by giving its source path", CUSTOM],
            'pgo': [False, "Enable profiling guided optimizations", CUSTOM],
            'mpiexec_cmd': ['srun -n ', "Command to run benchmarks to generate PGO profile. With -n switch", CUSTOM],
        })
        return extra_vars

    def pgo_steps(self):
        """
        Set of steps to be performed after the initial installation, if PGO were enabled
        """
        # Remove old profiles
        remove_dir(self.prof_dir)
        mkdir(self.prof_dir)

        # Clean the old build
        run_cmd('make distclean')

        # Compile and run example to generate profile
        print_msg("generating PGO profile...")
        write_file('pingpong.c', PINGPONG_PGO_TEST)
        run_cmd('%s/bin/mpicc pingpong.c -o pingpong' % self.installdir)
        run_cmd('PSM_SHM=0 %s 2 pingpong' % self.cfg['mpiexec_cmd'])
        run_cmd('PSM_SHM=1 %s 2 pingpong' % self.cfg['mpiexec_cmd'])

        # Check that the profiles are there
        new_profs = os.listdir(prof_dir)
        if not new_profs:
            raise EasyBuildError("The PGO profiles where not found in the expected directory (%s)" % prof_dir)

        # Change PGO related options
        self.cfg['pgo'] = False
        self.cfg['configopts'] = re.sub('--with-profile=gen', '--with-profile=use', self.cfg['configopts'])

        # Reconfigure
        print_msg("configuring with PGO...")
        self.configure_step()

        # Rebuild
        print_msg("building with PGO...")
        self.build_step()

        # Reinstall
        print_msg("installing with PGO...")
        self.install_step()


    # MPICH configure script complains when F90 or F90FLAGS are set,
    def configure_step(self):
        """
        Custom configuration procedure for ParaStationMPI.
        * Sets the correct options
        * Calls the MPICH configure_step, disabling the default MPICH options
        """

        comp_opts = {
            toolchain.GCC: 'gcc',
            toolchain.INTELCOMP: 'intel',
            # TODO: Include PGI as soon as it is available as toolchain
            #toolchain.PGI: 'pgi',
        }

        # Set confset
        comp_fam = self.toolchain.comp_family()
        if comp_fam in comp_opts:
            self.cfg.update('configopts', ' --with-confset=%s' % comp_opts[comp_fam])
        else:
            raise EasyBuildError("Compiler %s not supported. Valid options are: %s",
                                 comp_fam, ', '.join(comp_opts.keys()))

        # Enable threading, if necessary
        if self.cfg['threaded']:
            self.cfg.update('configopts', ' --with-threading')

        # Add extra mpich options, if any
        if self.cfg['mpich_opts'] is not None:
            self.cfg.update('configopts', ' --with-mpichconf="%s"' % self.cfg['mpich_opts'])

        # Add PGO related options, if enabled
        if self.cfg['pgo']:
            self.cfg.update('configopts', ' --with-profile=gen --with-profdir=%s' % self.prof_dir)

        # Lastly, set pscom related variables
        if self.cfg['pscom_allin_path'] is None:
            pscom_path = get_software_root('pscom')
        else:
            pscom_path = self.cfg['pscom_allin_path'].strip()
            self.cfg.update('configopts', ' --with-pscom-allin="%s"' % pscom_path)

        pscom_flags = 'PSCOM_LDFLAGS=-L{0}/lib PSCOM_CPPFLAGS=-I{0}/include'.format(pscom_path)
        self.cfg.update('preconfigopts', pscom_flags)

        super(EB_psmpi, self).configure_step(add_mpich_configopts=False)

    # If PGO is enabled, install, generate a profile, and start over
    def install_step(self):
        """
        Custom installation procedure for ParaStationMPI.
        * If PGO is requested, installs, generate a profile, and start over
        """
        super(EB_psmpi, self).install_step()

        if self.cfg['pgo']:
            self.pgo_steps()

    def sanity_check_step(self):
        """
        Disable the checking of the launchers for ParaStationMPI
        """
        # cfr. http://git.mpich.org/mpich.git/blob_plain/v3.1.1:/CHANGES
        # MPICH changed its library names sinceversion 3.1.1.
        # cfr. https://github.com/ParaStation/psmpi2/blob/master/ChangeLog
        # ParaStationMPI >= 5.1.1-1 is based on MPICH >= 3.1.3.
        # ParaStationMPI < 5.1.1-1 is based on MPICH < 3.1.1.
        use_new_libnames = LooseVersion(self.version) >= LooseVersion('5.1.1-1')

        super(EB_psmpi, self).sanity_check_step(use_new_libnames=use_new_libnames, check_launchers=False)
