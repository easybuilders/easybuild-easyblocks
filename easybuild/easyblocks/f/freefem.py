##
# Copyright 2009-2018 Ghent University
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
"""
import os

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.run import run_cmd
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root


class EB_FreeFem_plus__plus_(ConfigureMake):
    """Support for building and installing FreeFem++."""

    def configure_step(self):
        """FreeFem++ configure should run twice. First PETSc configured, then PETSc have to be build,
        then configure FreeFem++ with the built PETSc."""

        # first Autoreconf has to be run
        if not get_software_root('Autoconf'):
            raise EasyBuildError("Autoconf is required to build FreeFem++. Please add it as build dependency")

        run_cmd("autoreconf -i", log_all=True, simple=False)

        # delete old installation, then set keeppreviousinstall to True (do not delete PETsc install)
        self.make_installdir()
        self.cfg['keeppreviousinstall'] = True

        # configure and make petsc-slepc
        cmd = "./configure --prefix=%s &&" % self.installdir
        cmd += "cd download/ff-petsc &&"
        cmd += "make petsc-slepc &&"
        cmd += "cd ../.."
        run_cmd(cmd, log_all=True, simple=False)

        # check HDF5 and GSL deps and add the corresponding configopts
        hdf5_root = get_software_root('HDF5')
        if hdf5_root:
            self.cfg.update('configopts', '--with-hdf5=%s ' % os.path.join(hdf5_root, 'bin', 'h5pcc'))

        gsl_root = get_software_root('GSL')
        if gsl_root:
            self.cfg.update('configopts', '--with-gsl-include=%s ' % os.path.join(gsl_root, 'include'))
            self.cfg.update('configopts', '--with-gsl-ldflags=%s ' % os.path.join(gsl_root, 'lib'))

        # We should download deps
        self.cfg.update('configopts', '--enable-download ')

        # PaStiX does not work parallel, so disable it.
        self.cfg.update('configopts', '--disable-pastix ')

        super(EB_FreeFem_plus__plus_, self).configure_step()

    def build_step(self):
        # dependencies are heavily patched by FreeFem++, we therefore let it download and install them itself
        self.cfg.update('prebuildopts', 'download/getall -a -o ScaLAPACK,ARPACK,freeYams,Gmm++,Hips,Ipopt,METIS,'
                        'ParMETIS,MMG3D,mshmet,MUMPS,NLopt,pARMS,PaStiX,Scotch,SuiteSparse,SuperLU_DIST,SuperLU,'
                        'TetGen,PETSc,SLEPc,hpddm &&')

        # FreeFem++ parallel make does not work.
        if self.cfg['parallel'] != 1:
            self.log.warning("Ignoring requested build parallelism, it breaks FreeFem++ building, so setting to 1")
            self.cfg['parallel'] = 1

        super(EB_FreeFem_plus__plus_, self).build_step()

    def sanity_check_step(self):
        # define FreeFem++ sanity_check_paths here

        custom_paths = {
            'files': ['bin/%s' % x for x in ['bamg', 'cvmsh2', 'ffglut', 'ffmedit']] +
            ['bin/ff-%s' % x for x in ['c++', 'get-dep', 'mpirun', 'pkg-download']] +
            ['bin/FreeFem++%s' % x for x in ['', '-mpi', '-nw']],
            'dirs': ['share/freefem++/%s' % self.version] +
            ['lib/ff++/%s/%s' % (self.version, x) for x in ['bin', 'etc', 'idp', 'include', 'lib']]
        }
        super(EB_FreeFem_plus__plus_, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        # Run only one OpenBLAS thread
        txt = super(EB_FreeFem_plus__plus_, self).make_module_extra()
        txt += self.module_generator.set_environment('OPENBLAS_NUM_THREAD', "1")
        return txt
