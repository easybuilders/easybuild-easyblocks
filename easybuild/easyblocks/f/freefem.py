##
# Copyright 2009-2020 Ghent University
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
EasyBuild support for FreeFem++, implemented as an easyblock

@author: Balazs Hajgato (Free University Brussels - VUB)
@author: Kenneth Hoste (HPC-UGent)
"""
import os
import re

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root
from easybuild.tools.filetools import change_dir
from easybuild.tools.run import run_cmd


class EB_FreeFEM(ConfigureMake):
    """Support for building and installing FreeFem++."""

    def configure_step(self):
        """
        FreeFem++ configure should run twice.
        First to configure PETSc (and then build it),
        then to configure FreeFem++ with the built PETSc.
        """

        # first Autoreconf has to be run
        if not get_software_root('Autoconf'):
            raise EasyBuildError("Autoconf is required to build FreeFem++. Please add it as build dependency")

        run_cmd("autoreconf -i", log_all=True, simple=False)

        configopts = [
            '--disable-optim',  # disable custom optimizations (not needed, $CFLAGS set by EasyBuild is picked up)
            '--enable-download',  # enable downloading of dependencies
            '--disable-openblas',  # do not download OpenBLAS
        ]

        blas_family = self.toolchain.blas_family()
        if blas_family == toolchain.OPENBLAS:
            configopts.append("--with-blas=openblas")
        elif blas_family == toolchain.INTELMKL:
            mkl_root = get_software_root('imkl')
            configopts.append("--with-mkl=%s" % os.path.join(mkl_root, 'mkl', 'lib', 'intel64'))

        # check depencies and add the corresponding configure options for FreeFEM
        hdf5_root = get_software_root('HDF5')
        if hdf5_root:
            configopts.append('--with-hdf5=%s ' % os.path.join(hdf5_root, 'bin', 'h5pcc'))

        gsl_root = get_software_root('GSL')
        if gsl_root:
            configopts.append('--with-gsl-prefix=%s' % gsl_root)

        petsc_root = get_software_root('PETSc')
        if petsc_root:
            configopts.append('--with-petsc=%s' % os.path.join(petsc_root, 'lib', 'petsc', 'conf', 'petscvariables'))

        bemtool_root = get_software_root('BemTool')
        if bemtool_root:
            configopts.append('--with-bem-include=%s' % bemtool_root)

        for configopt in configopts:
            self.cfg.update('configopts', configopt)

        # initial configuration
        out = super(EB_FreeFEM, self).configure_step()

        regex = re.compile("WARNING: unrecognized options: (.*)", re.M)
        res = regex.search(out)
        if res:
            raise EasyBuildError("One or more configure options not recognized: %s" % res.group(1))

        if not petsc_root:
            # re-create installation dir (deletes old installation),
            # then set keeppreviousinstall to True (to avoid deleting PETSc installation)
            self.make_installdir()
            self.cfg['keeppreviousinstall'] = True

            # configure and make petsc-slepc
            # download & build PETSc as recommended by FreeFEM if no PETSc dependency was provided
            cwd = change_dir(os.path.join('3rdparty', 'ff-petsc'))

            cmd = ['make']
            if self.cfg['parallel']:
                cmd.append('-j %s' % self.cfg['parallel'])
            cmd.append('petsc-slepc')

            run_cmd(' '.join(cmd), log_all=True, simple=False)

            change_dir(cwd)

            # reconfigure for FreeFEM build
            super(EB_FreeFEM, self).configure_step()

    def test_step(self):
        """Run tests."""

        # run tests unless they're disabled explicitly
        if self.cfg['runtest'] is None or self.cfg['runtest']:
            # avoid oversubscribing, by using both OpenMP threads and having OpenBLAS use threads as well
            env.setvar('OPENBLAS_NUM_THREAD', '1')

            # avoid using too many OpenMP threads, which may slow tests down too much,
            # since this could lead to failing tests (60 sec. time limit is imposed by the test run script)
            parallel = self.cfg['parallel']
            if parallel:
                try:
                    par = int(parallel)
                except ValueError as err:
                    raise EasyBuildError("Failed to parse 'parallel' value '%s' as integer: %s", parallel)

                # use number of threads equal to 1/4th of available cores (and ensure at least one)
                n_thr = max(par // 4, 1)
            else:
                n_thr = 1

            env.setvar('OMP_NUM_THREADS', '%d' % n_thr)

            run_cmd("make check", log_all=True, simple=False)

    def sanity_check_step(self):
        # define FreeFem++ sanity_check_paths here

        custom_paths = {
            'files': ['bin/%s' % x for x in ['bamg', 'cvmsh2', 'ffglut', 'ffmedit']] +
                     ['bin/ff-%s' % x for x in ['c++', 'get-dep', 'mpirun', 'pkg-download']] +
                     ['bin/FreeFem++%s' % x for x in ['', '-mpi', '-nw']],
            'dirs': ['share/FreeFEM/%s' % self.version] +
                    ['lib/ff++/%s/%s' % (self.version, x) for x in ['bin', 'etc', 'idp', 'include', 'lib']]
        }
        super(EB_FreeFEM, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        txt = super(EB_FreeFEM, self).make_module_extra()
        if blas_family == toolchain.OPENBLAS:
            # Run only one OpenBLAS thread
            txt += self.module_generator.set_environment('OPENBLAS_NUM_THREAD', "1")
        return txt
