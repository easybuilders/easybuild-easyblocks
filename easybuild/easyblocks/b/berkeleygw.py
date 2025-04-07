##
# Copyright 2009-2025 Ghent University
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
EasyBuild support for BerkeleyGW, implemented as an easyblock

@author: Miguel Dias Costa (National University of Singapore)
"""
import os
from easybuild.tools import LooseVersion

import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.environment import setvar
from easybuild.tools.filetools import copy_file
from easybuild.tools.modules import get_software_root, get_software_version


class EB_BerkeleyGW(ConfigureMake):
    """Support for building and installing BerkeleyGW."""

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for BerkeleyGW."""
        extra_vars = {
            'with_scalapack': [True, "Enable ScaLAPACK support", CUSTOM],
            'unpacked': [False, "Use unpacked rather than packed representation of the Hamiltonian", CUSTOM],
        }
        return ConfigureMake.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Add extra config options specific to BerkeleyGW."""
        super(EB_BerkeleyGW, self).__init__(*args, **kwargs)

    def configure_step(self):
        """No configuration procedure for BerkeleyGW."""
        pass

    def build_step(self):
        """Custom build step for BerkeleyGW."""

        self.cfg.parallel = 1

        self.cfg['buildopts'] = 'all-flavors'

        copy_file(os.path.join('config', 'generic.mpi.linux.mk'), 'arch.mk')

        mpicc = os.environ['MPICC']
        mpicxx = os.environ['MPICXX']
        mpif90 = os.environ['MPIF90']

        paraflags = []
        var_suffix = ''
        if self.toolchain.options.get('openmp', None):
            paraflags.append('-DOMP')
            var_suffix = '_MT'
        if self.toolchain.options.get('usempi', None):
            paraflags.append('-DMPI')
            self.cfg.update('buildopts', 'C_PARAFLAG="-DPARA"')
        self.cfg.update('buildopts', 'PARAFLAG="%s"' % ' '.join(paraflags))

        if self.toolchain.options.get('debug', None):
            self.cfg.update('buildopts', 'DEBUGFLAG="-DDEBUG -DVERBOSE"')
        else:
            self.cfg.update('buildopts', 'DEBUGFLAG=""')

        self.cfg.update('buildopts', 'LINK="%s"' % mpif90)
        self.cfg.update('buildopts', 'C_LINK="%s"' % mpicxx)

        self.cfg.update('buildopts', 'FOPTS="%s"' % os.environ['FFLAGS'])
        self.cfg.update('buildopts', 'C_OPTS="%s"' % os.environ['CFLAGS'])

        self.cfg.update('buildopts', 'LAPACKLIB="%s"' % os.environ['LIBLAPACK' + var_suffix])
        self.cfg.update('buildopts', 'SCALAPACKLIB="%s"' % os.environ['LIBSCALAPACK' + var_suffix])

        mathflags = []
        if self.cfg['with_scalapack']:
            mathflags.append('-DUSESCALAPACK')
        if self.cfg['unpacked']:
            mathflags.append('-DUNPACKED')

        comp_fam = self.toolchain.comp_family()
        if comp_fam == toolchain.INTELCOMP:
            self.cfg.update('buildopts', 'COMPFLAG="-DINTEL"')
            self.cfg.update('buildopts', 'MOD_OPT="-module "')
            self.cfg.update('buildopts', 'F90free="%s -free"' % mpif90)
            self.cfg.update('buildopts', 'FCPP="cpp -C -P -ffreestanding"')
            self.cfg.update('buildopts', 'C_COMP="%s"' % mpicc)
            self.cfg.update('buildopts', 'CC_COMP="%s"' % mpicxx)
            self.cfg.update('buildopts', 'BLACSDIR="%s"' % os.environ['BLACS_LIB_DIR'])
            self.cfg.update('buildopts', 'BLACS="%s"' % os.environ['LIBBLACS'])
        elif comp_fam == toolchain.GCC:
            c_flags = "-std=c99"
            cxx_flags = "-std=c++0x"
            f90_flags = "-ffree-form -ffree-line-length-none -fno-second-underscore"
            if LooseVersion(get_software_version('GCC')) >= LooseVersion('10'):
                c_flags += " -fcommon"
                cxx_flags += " -fcommon"
                f90_flags += " -fallow-argument-mismatch"
            self.cfg.update('buildopts', 'COMPFLAG="-DGNU"')
            self.cfg.update('buildopts', 'MOD_OPT="-J "')
            self.cfg.update('buildopts', 'F90free="%s %s"' % (mpif90, f90_flags))
            self.cfg.update('buildopts', 'FCPP="cpp -C -nostdinc -nostdinc++"')
            self.cfg.update('buildopts', 'C_COMP="%s %s"' % (mpicc, c_flags))
            self.cfg.update('buildopts', 'CC_COMP="%s %s"' % (mpicxx, cxx_flags))
        else:
            raise EasyBuildError("EasyBuild does not yet have support for building BerkeleyGW with toolchain %s"
                                 % comp_fam)

        mkl = get_software_root('imkl')
        if mkl:
            self.cfg.update('buildopts', 'MKLPATH="%s"' % os.getenv('MKLROOT'))

        fftw = get_software_root('FFTW')
        if mkl or fftw:
            mathflags.append('-DUSEFFTW3')
            self.cfg.update('buildopts', 'FFTWINCLUDE="%s"' % os.environ['FFTW_INC_DIR'])

            libfft_var = 'LIBFFT%s' % var_suffix
            fft_libs = os.environ[libfft_var]

            if fftw and get_software_root('fftlib'):
                fft_libs = "%s %s" % (os.environ['FFTLIB'], fft_libs)

            self.cfg.update('buildopts', 'FFTWLIB="%s"' % fft_libs)

        hdf5 = get_software_root('HDF5')
        if hdf5:
            mathflags.append('-DHDF5')
            self.cfg.update('buildopts', 'HDF5INCLUDE="%s/include"' % hdf5)
            self.cfg.update('buildopts', 'HDF5LIB="-L%s/lib -lhdf5hl_fortran -lhdf5_hl -lhdf5_fortran -lhdf5 -lsz -lz"'
                            % hdf5)

        elpa = get_software_root('ELPA')
        if elpa:
            if not self.cfg['with_scalapack']:
                raise EasyBuildError("ELPA requires ScaLAPACK but 'with_scalapack' is set to False")
            mathflags.append('-DUSEELPA')
            elpa_suffix = '_openmp' if self.toolchain.options.get('openmp', None) else ''
            self.cfg.update('buildopts', 'ELPALIB="%s/lib/libelpa%s.a"' % (elpa, elpa_suffix))
            self.cfg.update('buildopts', 'ELPAINCLUDE="%s/include/elpa%s-%s/modules"'
                            % (elpa, elpa_suffix, get_software_version('ELPA')))

        self.cfg.update('buildopts', 'MATHFLAG="%s"' % ' '.join(mathflags))

        super(EB_BerkeleyGW, self).build_step()

    def install_step(self):
        """Custom install step for BerkeleyGW."""
        self.cfg.update('installopts', 'INSTDIR="%s"' % self.installdir)
        super(EB_BerkeleyGW, self).install_step()

    def test_step(self):
        """Custom test step for BerkeleyGW."""
        if self.cfg['runtest'] is not False:
            self.cfg['runtest'] = 'check'
            setvar('BGW_TEST_MPI_NPROCS', '2')
            setvar('OMP_NUM_THREADS', '2')
            setvar('TEMPDIRPATH', os.path.join(self.builddir, 'tmp'))
        super(EB_BerkeleyGW, self).test_step()

    def sanity_check_step(self):
        """Custom sanity check for BerkeleyGW."""

        progs = ['epsilon', 'sigma', 'kernel', 'absorption', 'nonlinearoptics', 'parabands']
        flavors = ['real', 'cplx']
        files = [os.path.join('bin', prog + '.' + flavor + '.x') for prog in progs for flavor in flavors]

        custom_paths = {
            'files': files,
            'dirs': [],
        }

        super(EB_BerkeleyGW, self).sanity_check_step(custom_paths=custom_paths)
