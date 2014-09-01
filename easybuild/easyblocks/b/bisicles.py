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
EasyBuild support for BISICLES, implemented as an easyblock

@author: Balazs Hajgato (VUB)
"""
import os
import easybuild.tools.toolchain as toolchain

from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.modules import get_software_root, get_software_libdir
from easybuild.tools.filetools import run_cmd


class EB_BISICLES(EasyBlock):
    """Support for building and installing BISICLES."""

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for BISICLES."""
        super(EB_BISICLES, self).__init__(*args, **kwargs)

        self.make_options = None

    def configure_step(self):
        """No configure step for BISICLES."""
        pass

    def build_step(self):
        """Build BISICLES."""
        self.make_options = "DEBUG=FALSE OPT=TRUE PRECISION=DOUBLE USE_COMPLEX=TRUE "
        self.make_options += "USE_TIMER=TRUE USE_MT=TRUE "
        self.make_options += "USE_HDF=TRUE USE_64=TRUE "
#Ugly but no better idea:
        for file in os.listdir(self.builddir):
            if file.startswith("Chombo-"):
                chombo_home = self.builddir + "/" + file
        self.make_options += "CHOMBO_HOME=%s/lib " % chombo_home
        self.make_options += "BISICLES_HOME=%s/BISICLES-%s " % (self.builddir,self.version)
        self.make_options += "NETCDF_HOME=%s " % os.getenv('EBROOTNETCDF')
        self.make_options += 'HDFINCFLAGS="-I%s/include" ' % os.getenv('EBROOTHDF5') 
        self.make_options += 'HDFLIBFLAGS="-L%s/%s -lhdf5 -lz" ' % (os.getenv('EBROOTHDF5'),get_software_libdir('HDF5'))

        self.make_options += "CXX=%s FC=%s " % (os.getenv('CXX'),os.getenv('F90'))
        self.make_options += 'CFLAGS="%s" ' % (os.getenv('CFLAGS'))
        self.make_options += 'CXXLAGS="%s" ' % (os.getenv('CXXFLAGS'))
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

        cmd = "cd %s/lib && make setup" % chombo_home
        run_cmd(cmd, log_all=True, simple=False)
        
        if self.cfg['parallel']:
           paropts = "-j %s" % self.cfg['parallel']

        for programbuild in ['exec2D', 'filetools', 'controlproblem']:
            cmd = "cd %s/BISICLES-%s/code/%s && make %s DIM=2 %s all" % (self.builddir,self.version,programbuild,paropts,self.make_options)
            run_cmd(cmd, log_all=True, simple=False)

    def test_step(self):
        """No testsuite provided with the source"""
        pass

    def install_step(self):
        """Custom install procedure for BISICLES."""

        cmd = "mkdir {0}/bin && mv code/{{exec2D,filetools}}/*.ex {0}/bin ".format(self.installdir)
        run_cmd(cmd, log_all=True, simple=True)

        cmd = "mv code/controlproblem/c*.ex {0}/bin ".format(self.installdir)
        run_cmd(cmd, log_all=True, simple=True)

    def sanity_check_step(self):
        """Custom sanity check for BISICLES."""

        libsuff = "2d.Linux.64.%s.%s.OPT" % (os.getenv('CXX'),os.getenv('F90'))
        if self.toolchain.options.get('usempi', None):
            libsuff += ".MPI"

        if  get_software_root("PETSc"):
            libsuff += ".PETSC"

        if self.toolchain.options['pic']:
            libsuff += ".pic"

        checkexecs = ['driver', 'nctoamr', 'amrtotxt', 'amrtoplot', 'flatten',
                      'extract', 'merge', 'addbox', 'amrtocf', 'stats',
                      'glfaces', 'faces', 'rescale', 'sum', 'pythonf', 
                      'control', 
                     ]

        sanity_check_paths = {
            'files': ['bin/%s%s' % (execs, libsuff) for execs in checkexecs],
            'dirs': [],
        }
