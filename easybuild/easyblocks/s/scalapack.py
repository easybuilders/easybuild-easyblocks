##
# Copyright 2009-2024 Ghent University
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
EasyBuild support for building and installing ScaLAPACK, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""

import glob
import os
from easybuild.tools import LooseVersion

import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.blacs import det_interface  # @UnresolvedImport
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.toolchains.linalg.acml import Acml
from easybuild.toolchains.linalg.atlas import Atlas
from easybuild.toolchains.linalg.blacs import Blacs
from easybuild.toolchains.linalg.blis import Blis
from easybuild.toolchains.linalg.flexiblas import FlexiBLAS, det_flexiblas_backend_libs
from easybuild.toolchains.linalg.gotoblas import GotoBLAS
from easybuild.toolchains.linalg.lapack import Lapack
from easybuild.toolchains.linalg.openblas import OpenBLAS
from easybuild.toolchains.linalg.intelmkl import IntelMKL
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import copy_file, remove_file
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd


class EB_ScaLAPACK(CMakeMake):
    """
    Support for building and installing ScaLAPACK, both versions 1.x and 2.x
    """

    def __init__(self, *args, **kwargs):
        """Constructor of ScaLAPACK easyblock."""
        super(EB_ScaLAPACK, self).__init__(*args, **kwargs)

        self.loosever = LooseVersion(self.version)

        # use CMake for recent versions, but only if CMake is listed as a build dep
        build_deps_names = [dep['name'].lower() for dep in self.cfg.builddependencies()]
        self.use_cmake = self.loosever >= LooseVersion('2.1.0') and 'cmake' in build_deps_names

    def configure_step(self):
        """Configure ScaLAPACK build by copying SLmake.inc.example to SLmake.inc and checking dependencies."""

        # use CMake for recent versions, but only if CMake is listed as a build dep
        if self.use_cmake:
            super(EB_ScaLAPACK, self).configure_step()
        else:
            src = os.path.join(self.cfg['start_dir'], 'SLmake.inc.example')
            dest = os.path.join(self.cfg['start_dir'], 'SLmake.inc')

            if os.path.exists(dest):
                raise EasyBuildError("Destination file %s exists", dest)
            else:
                copy_file(src, dest)

    def build_libscalapack_make(self):
        """Build libscalapack using 'make -j', after determining the options to pass to make."""
        # MPI compiler commands
        known_mpi_libs = [toolchain.MPICH, toolchain.MPICH2, toolchain.MVAPICH2]  # @UndefinedVariable
        known_mpi_libs += [toolchain.OPENMPI, toolchain.QLOGICMPI]  # @UndefinedVariable
        known_mpi_libs += [toolchain.INTELMPI]  # @UndefinedVariable
        if os.getenv('MPICC') and os.getenv('MPIF77') and os.getenv('MPIF90'):
            mpicc = os.getenv('MPICC')
            mpif77 = os.getenv('MPIF77')
            mpif90 = os.getenv('MPIF90')
        elif self.toolchain.mpi_family() in known_mpi_libs:
            mpicc = 'mpicc'
            mpif77 = 'mpif77'
            mpif90 = 'mpif90'
        else:
            raise EasyBuildError("Don't know which compiler commands to use.")

        # determine build options BLAS and LAPACK libs
        extra_makeopts = []

        acml = get_software_root(Acml.LAPACK_MODULE_NAME[0])
        flexiblas = get_software_root(FlexiBLAS.LAPACK_MODULE_NAME[0])
        intelmkl = get_software_root(IntelMKL.LAPACK_MODULE_NAME[0])
        lapack = get_software_root(Lapack.LAPACK_MODULE_NAME[0])
        openblas = get_software_root(OpenBLAS.LAPACK_MODULE_NAME[0])

        if flexiblas:
            libdir = os.path.join(flexiblas, 'lib')
            blas_libs = ' '.join(['-l%s' % lib for lib in FlexiBLAS.BLAS_LIB])
            extra_makeopts.extend([
                'BLASLIB="-L%s %s -lpthread"' % (libdir, blas_libs),
                'LAPACKLIB="-L%s %s"' % (libdir, blas_libs),
            ])
        elif lapack:
            extra_makeopts.append('LAPACKLIB=%s' % os.path.join(lapack, 'lib', 'liblapack.a'))

            for blas in [Atlas, Blis, GotoBLAS]:
                blas_root = get_software_root(blas.BLAS_MODULE_NAME[0])
                if blas_root:
                    blas_libs = ' '.join(['-l%s' % lib for lib in blas.BLAS_LIB])
                    blas_libdir = os.path.join(blas_root, 'lib')
                    extra_makeopts.append('BLASLIB="-L%s %s -lpthread"' % (blas_libdir, blas_libs))
                    break

            if not blas_root:
                raise EasyBuildError("Failed to find a known BLAS library, don't know how to define 'BLASLIB'")

        elif acml:
            acml_base_dir = os.getenv('ACML_BASEDIR', 'NO_ACML_BASEDIR')
            acml_static_lib = os.path.join(acml, acml_base_dir, 'lib', 'libacml.a')
            extra_makeopts.extend([
                'BLASLIB="%s -lpthread"' % acml_static_lib,
                'LAPACKLIB=%s' % acml_static_lib
            ])
        elif openblas:
            libdir = os.path.join(openblas, 'lib')
            blas_libs = ' '.join(['-l%s' % lib for lib in OpenBLAS.BLAS_LIB])
            extra_makeopts.extend([
                'BLASLIB="-L%s %s -lpthread"' % (libdir, blas_libs),
                'LAPACKLIB="-L%s %s"' % (libdir, blas_libs),
            ])
        elif intelmkl:
            libdir = os.path.join(intelmkl, 'mkl', 'lib', 'intel64')
            blas_libs = os.environ['LIBLAPACK']
            extra_makeopts.extend([
                'BLASLIB="-L%s %s -lpthread"' % (libdir, blas_libs),
                'LAPACKLIB="-L%s %s"' % (libdir, blas_libs),
            ])
        else:
            raise EasyBuildError("Unknown LAPACK library used, no idea how to set BLASLIB/LAPACKLIB make options")

        # build procedure changed in v2.0.0
        if self.loosever < LooseVersion('2.0.0'):

            blacs = get_software_root(Blacs.BLACS_MODULE_NAME[0])
            if not blacs:
                raise EasyBuildError("BLACS not available, yet required for ScaLAPACK version < 2.0.0")

            # determine interface
            interface = det_interface(self.log, os.path.join(blacs, 'bin'))

            # set build and BLACS dir correctly
            extra_makeopts.append('home=%s BLACSdir=%s' % (self.cfg['start_dir'], blacs))

            # set BLACS libs correctly
            blacs_libs = [
                ('BLACSFINIT', "F77init"),
                ('BLACSCINIT', "Cinit"),
                ('BLACSLIB', "")
            ]
            for (var, lib) in blacs_libs:
                extra_makeopts.append('%s=%s/lib/libblacs%s.a' % (var, blacs, lib))

            # set compilers and options
            noopt = ''
            if self.toolchain.options['noopt']:
                noopt += " -O0"
            if self.toolchain.options['pic']:
                noopt += " -fPIC"
            extra_makeopts += [
                'F77="%s"' % mpif77,
                'CC="%s"' % mpicc,
                'NOOPT="%s"' % noopt,
                'CCFLAGS="-O3 %s"' % os.getenv('CFLAGS')
            ]

            # set interface
            extra_makeopts.append("CDEFS='-D%s -DNO_IEEE $(USEMPI)'" % interface)

        else:

            # determine interface
            if self.toolchain.mpi_family() in known_mpi_libs:
                interface = 'Add_'
            else:
                raise EasyBuildError("Don't know which interface to pick for the MPI library being used.")

            # set compilers and options
            extra_makeopts += [
                'FC="%s"' % mpif90,
                'CC="%s"' % mpicc,
                'CCFLAGS="%s"' % os.getenv('CFLAGS'),
                'FCFLAGS="%s"' % os.getenv('FFLAGS'),
            ]

            # set interface
            extra_makeopts.append('CDEFS="-D%s"' % interface)

        # update make opts, and build_step
        saved_buildopts = self.cfg['buildopts']

        # Only build the library first, that can be done in parallel.
        # Creating libscalapack.a may fail in parallel, but should work
        # fine with non-parallel make afterwards
        self.cfg.update('buildopts', 'lib')
        self.cfg.update('buildopts', ' '.join(extra_makeopts))

        # Copied from ConfigureMake easyblock
        paracmd = ''
        if self.cfg['parallel']:
            paracmd = "-j %s" % self.cfg['parallel']

        cmd = "%s make %s %s" % (self.cfg['prebuildopts'], paracmd, self.cfg['buildopts'])

        # Ignore exit code for parallel run
        (out, _) = run_cmd(cmd, log_ok=False, log_all=False, simple=False)

        # Now prepare to remake libscalapack.a serially and the tests.
        self.cfg['buildopts'] = saved_buildopts
        self.cfg.update('buildopts', ' '.join(extra_makeopts))

        remove_file('libscalapack.a')
        self.cfg['parallel'] = 1

    def build_step(self):
        """Build ScaLAPACK using make after setting make options."""

        # only do a parallel pre-build of libscalapack and set up build options if we're not using CMake
        if not self.use_cmake:
            self.build_libscalapack_make()

        super(EB_ScaLAPACK, self).build_step()

    def install_step(self):
        """Install by copying files to install dir."""

        if self.use_cmake:
            super(EB_ScaLAPACK, self).install_step()
        else:
            # 'manually' install ScaLAPACK by copying headers and libraries if we're not using CMake
            path_info = [
                ('SRC', 'include', '.h'),  # include files
                ('', 'lib', '.a'),  # libraries
            ]
            for (srcdir, destdir, ext) in path_info:

                src = os.path.join(self.cfg['start_dir'], srcdir)
                dest = os.path.join(self.installdir, destdir)

                for lib in glob.glob(os.path.join(src, '*%s' % ext)):
                    copy_file(lib, os.path.join(dest, os.path.basename(lib)))
                    self.log.debug("Copied %s to %s", lib, dest)

    def banned_linked_shared_libs(self):
        """
        List of shared libraries which are not allowed to be linked in any installed binary/library.
        """
        res = super(EB_ScaLAPACK, self).banned_linked_shared_libs()

        # register FlexiBLAS backends as banned libraries,
        # ScaLAPACK should not be linking to those directly
        if get_software_root(FlexiBLAS.LAPACK_MODULE_NAME[0]):
            res.extend(det_flexiblas_backend_libs())

        return res

    def sanity_check_step(self):
        """Custom sanity check for ScaLAPACK."""

        custom_paths = {
            'files': [os.path.join('lib', 'libscalapack.a')],
            'dirs': []
        }

        super(EB_ScaLAPACK, self).sanity_check_step(custom_paths=custom_paths)
