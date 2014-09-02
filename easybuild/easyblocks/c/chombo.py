##
# Copyright 2009-2013 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# the Hercules foundation (http://www.herculesstichting.be/in_English)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
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
EasyBuild support for Chombo, implemented as an easyblock

@author: Balazs Hajgato (VUB)
"""
import os
import easybuild.tools.toolchain as toolchain

from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.modules import get_software_root, get_software_libdir
from easybuild.tools.filetools import run_cmd


class EB_Chombo(EasyBlock):
    """Support for building and installing Chombo."""

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for Chombo."""
        super(EB_Chombo, self).__init__(*args, **kwargs)

        self.make_options = None

    def configure_step(self):
        """No configure step for Chombo."""
        pass

    def build_step(self):
        """Build Chombo."""
        run_cmd("make setup")
       
        self.make_options = "DEBUG=FALSE OPT=TRUE PRECISION=DOUBLE USE_COMPLEX=TRUE "
        self.make_options += "USE_TIMER=TRUE USE_CCSE=TRUE USE_MT=TRUE "
        self.make_options += "USE_HDF=TRUE USE_64=TRUE "
        self.make_options += 'HDFINCFLAGS="-I%s/include" ' % os.getenv('EBROOTHDF5') 
        self.make_options += 'HDFLIBFLAGS="-L%s/%s -lhdf5 -lz" ' % (os.getenv('EBROOTHDF5'),get_software_libdir('HDF5'))

        self.make_options += "CXX=%s FC=%s " % (os.getenv('CXX'),os.getenv('F90'))
        self.make_options += 'CFLAGS="%s" ' % (os.getenv('CFLAGS'))
        self.make_options += 'CXXFLAGS="%s" ' % (os.getenv('CXXFLAGS'))
        self.make_options += 'FCFLAGS="%s" ' % (os.getenv('F90FLAGS'))

        if self.toolchain.options['pic']:
            self.make_options += "PIC=TRUE "
        
        if self.toolchain.options.get('usempi', None):
            self.make_options += "MPI=TRUE MPICXX=%s MPICC=%s " % (os.getenv('MPICXX'),os.getenv('MPICC'))
            self.make_options += 'HDFMPIINCFLAGS="-I%s/include" ' % os.getenv('EBROOTHDF5')
            self.make_options += 'HDFMPILIBFLAGS="-L%s/%s -lhdf5 -lz" ' % (os.getenv('EBROOTHDF5'),get_software_libdir('HDF5'))
            
        if get_software_root("Python"):
            self.make_options += "USE_PYTHON=TRUE "

        if get_software_root("PETSc"):
            self.make_options += "USE_PETSC=TRUE "

        if self.cfg['parallel']:
           paropts = "-j %s" % self.cfg['parallel']

        for dim in range(1,7):
            if (dim==2 or dim==3):
                seteb = "USE_EB=TRUE"
            else:
                seteb = ""
            cmd = "make %s DIM=%s %s %s all" % (paropts, dim, seteb, self.make_options)
            run_cmd(cmd, log_all=True, simple=False)
 
    def test_step(self):
        """Run the testsuite"""

# test with dim=6 requires about 120Gb RAM so, it is switched off
# test with dim=5 takes a good one hour, so maybe it has to be switched off.
        for dim in range(1,6):
            if (dim==2 or dim==3):
                seteb = "USE_EB=TRUE"
            else:
                seteb = ""
# test does not pass if make run parallel
            cmd = "make DIM=%s %s %s run" % (dim, seteb, self.make_options)
            run_cmd(cmd, log_all=True, simple=False)

    def install_step(self):
        """Custom install procedure for Chombo."""

        cmd = "mkdir {0}/lib && mv lib* {0}/lib && mv include {0}".format(self.installdir)

        run_cmd(cmd, log_all=True, simple=True)

    def sanity_check_step(self):
        """Custom sanity check for Chombo."""

        libsuff = "d.Linux.64.%s.%s.OPT" % (os.getenv('CXX'),os.getenv('F90'))
        if self.toolchain.options.get('usempi', None):
            libsuff += ".MPI"

        if  get_software_root("PETSc"):
            libsuff += ".PETSC"

        if self.toolchain.options['pic']:
            libsuff += ".pic"

        checklibs = ['%s%s' % ('armelliptic', dims) for dims in range(1,4)]
        checklibs += ['%s%s' % ('amrtimedependent', dims) for dims in range(1,7)]
        checklibs += ['%s%s' % ('amrtools', dims) for dims in range(1,7)]
        checklibs += ['%s%s' % ('basetools', dims) for dims in range(1,7)]
        checklibs += ['%s%s' % ('ebamrtimedependent', dims) for dims in range(2,4)]
        checklibs += ['%s%s' % ('ebamrtimedependent', dims) for dims in range(2,4)]
        checklibs += ['%s%s' % ('ebamrtools', dims) for dims in range(2,4)]
        checklibs += ['%s%s' % ('ebtools', dims) for dims in range(2,4)]
        checklibs += ['%s%s' % ('workshop', dims) for dims in range(2,4)]
        sanity_check_paths = {
            'files': ['lib/lib%s%s' % (libs, libsuff) for libs in checklibs],
            'dirs': ['include'],
        }
