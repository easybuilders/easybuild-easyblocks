##
# Copyright 2009-2015 Ghent University
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
EasyBuild support for building and installing LAMMPS, implemented as an easyblock
 
@author: Kenneth Hoste (Ghent University)
@author: Alexander Schnurpfeil (Juelich Supercomputer Centre)
"""
import os

import easybuild.tools.toolchain as toolchain
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import MANDATORY
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.run import run_cmd


class EB_LAMMPS(EasyBlock):
    """Support for building/installing LAMMPS."""

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for LAMMPS."""
        super(EB_LAMMPS, self).__init__(*args, **kwargs)

        self.build_in_installdir = True

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for LAMMPS."""
        extra_vars = {
            'packages': [[], "LAMMPS packages to install", MANDATORY],
        }
        return EasyBlock.extra_options(extra_vars)

    def extract_step(self):
        """Extract LAMMPS sources."""
        # strip off top-level subdirectory
        self.cfg.update('unpack_options', '--strip-components=1')
        super(EB_LAMMPS, self).extract_step()

    def configure_step(self):
        """No configure step for LAMMPS."""
        pass

    def build_step(self):
        """Custom build procedure for LAMMPS."""

        def find_makefile():
            """Find Makefile, by considering each of the Fortran/C++/C compilers."""

        libdir = os.path.join(self.cfg['start_dir'], 'lib')
        srcdir = os.path.join(self.cfg['start_dir'], 'src')

        cc = os.getenv('CC')
        cxx = os.getenv('CXX')
        f90 = os.getenv('F90')
        suffixes = [
            # MPI wrappers should be considered first
            'mpicc',
            'mpic++',
            # active serial compilers next
            cc,
            cxx,
            f90,
            # GNU compilers as backup (in case no custom Makefile for active compiler is available)
            'gcc',
            'g++',
            'gfortran',
            # generic fallback
            'lammps',
        ]

        # build all packages
        # skipped:
        # * cuda
        # * gpu
        # * kim (requires external dep, see https://openkim.org)
        # * 
        for pkg in [p for p in os.listdir(libdir) if p not in ['README', 'cuda', 'gpu', 'kim', 'kokkos', 'molfile',
                                                               'voronoi', 'linalg']]:

            pkglibdir = os.path.join(libdir, pkg)
            if os.path.exists(pkglibdir):
                try:
                    os.chdir(pkglibdir)
                except OSError as err:
                    raise EasyBuildError("Failed to change to %s: %s", pkglibdir, err)

                self.log.info("Building %s package libraries in %s" % (pkg, pkglibdir))

                makefile = None
                for suffix in suffixes:
                    pot_makefile = 'Makefile.%s' % suffix
                    self.log.debug("Checking for %s in %s" % (pot_makefile, pkglibdir))
                    if os.path.exists(pot_makefile):
                        makefile = pot_makefile
                        self.log.debug("Found %s in %s" % (makefile, pkglibdir))
                        break

                if makefile is None:
                    raise EasyBuildError("No makefile matching active compilers found in %s", pkglibdir)

                # make sure active compiler is used
                run_cmd('make -f %s CC="%s" CXX="%s" FC="%s"' % (makefile, cc, cxx, f90), log_output=True)

            try:
                os.chdir(srcdir)
            except OSError as err:
                raise EasyBuildError("Failed to change to %s: %s", srcdir, err)

        for p in self.cfg['packages']:
            self.log.info("Building %s package", p)
            run_cmd("make yes-%s" % p, log_output=True)

        # build LAMMPS itself
        run_cmd("make mpi", log_output=True)

    def install_step(self):
        """No separate install step for LAMMPS."""
        pass

    def sanity_check_step(self):
        """Custom sanity check for LAMMPS."""
        custom_paths = {
            'files': ['file1', 'file2'],
            'dirs': ['dir1', 'dir2'],
        }
        super(EB_LAMMPS, self).sanity_check_step(custom_paths=custom_paths)
