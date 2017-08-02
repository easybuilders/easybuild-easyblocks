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
@author: Maxime Boissonneault (Compute Canada)
@author: Ali Kerrache (Compute Canada)
"""
import os

import easybuild.tools.toolchain as toolchain
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import MANDATORY
from easybuild.framework.easyconfig import CUSTOM
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
            'packages_yes': [[], "LAMMPS packages to install", MANDATORY],
            'packages_no': [[], "LAMMPS packages to avoid installing", CUSTOM],
            'packaged_libraries': [[], "Libraries to package with LAMMPS", MANDATORY],
            'build_shared_libs': [True, "Build shared libraries" , CUSTOM],
            'build_static_libs': [True, "Build static libraries", CUSTOM],
            'build_type': ["", 'Argument passed to "make" for building LAMMPS itself', CUSTOM],
        }
        return EasyBlock.extra_options(extra_vars)

    def extract_step(self):
        """Extract LAMMPS sources."""
        # strip off top-level subdirectory
        # self.cfg.update('unpack_options', '--strip-components=1')
        self.cfg['unpack_options'] = "--strip-components=1"
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
            # MPI wrappers should be considered first:
            'mpicc',
            'mpic++',
            # Active serial compilers next:
            cc,
            cxx,
            f90,
            # GNU compilers as backup (in case no custom Makefile for active compiler is available):
            'gcc',
            'g++',
            'gfortran',
            # Generic fallback:
            'lammps',
            # In case there is just a Makefile without extension:
            ''
        ]

        # Build all packages and libraries:

        for pkg_t in self.cfg['packaged_libraries']:
            makefile_ = None
            if type(pkg_t) is tuple:
                pkg, makefile_ = pkg_t
            else:
                pkg = pkg_t

            pkglibdir = os.path.join(libdir, pkg)
            if os.path.exists(pkglibdir):
                try:
                    os.chdir(pkglibdir)
                except OSError as err:
                    raise EasyBuildError("Failed to change to %s: %s", pkglibdir, err)

                self.log.info("Building %s package libraries in %s" % (pkg, pkglibdir))

                if makefile_:
                    makefile = makefile_
                else:
                    makefile = None
                    for suffix in suffixes:
                        if suffix:
                            pot_makefile = 'Makefile.%s' % suffix
                        else:
                            pot_makefile = 'Makefile'

                        self.log.debug("Checking for %s in %s" % (pot_makefile, pkglibdir))
                        if os.path.exists(pot_makefile):
                            makefile = pot_makefile
                            self.log.debug("Found %s in %s" % (makefile, pkglibdir))
                            break

                if makefile is None:
                    raise EasyBuildError("No makefile matching active compilers found in %s", pkglibdir)

                # Make sure active compiler is used:

                run_cmd('make -f %s CC="%s" CXX="%s" FC="%s"' % (makefile, cc, cxx, f90), log_all=True)

            try:
                os.chdir(srcdir)
            except OSError as err:
                raise EasyBuildError("Failed to change to %s: %s", srcdir, err)

        for p in self.cfg['packages_yes']:
            self.log.info("Building %s package", p)
            run_cmd("make yes-%s" % p, log_all=True)

        for p in self.cfg['packages_no']:
            self.log.info("Building %s package", p)
            run_cmd("make no-%s" % p, log_all=True)

        # Build QUIP LIBRARY:

        #if self.cfg["build_quip_libs"]:
        #    run_cmd("cd ../lib/quip")
        #    run_cmd("cd ../../src/")

        # Build KOKKOS:

        #run_cmd("mkdir -p ../lib/kokos/build && pushd ../lib/kokos/build && cmake .. && make && popd " )

        # Save the list of built packages:

        run_cmd("echo Supported Packages: > list-packages.txt")
        run_cmd("make package-status | grep -a 'YES:' >> list-packages.txt")
        run_cmd("echo Not Supported Packages: >> list-packages.txt")
        run_cmd("make package-status | grep -a 'NO:' >> list-packages.txt")
        run_cmd("make package-update")

        # Build LAMMPS itself:

        build_type = self.cfg["build_type"]
        run_cmd("make %s" % build_type, log_all=True)

        # Build shared libraries:

        if self.cfg["build_shared_libs"]:
            run_cmd("make mode=shlib %s" % build_type, log_all=True)

        # Build static libraries:

        if self.cfg["build_static_libs"]:
            run_cmd("make mode=lib %s" % build_type, log_all=True)

    # Copy files and directories to the installation directory:

    def install_step(self):
        """Copying files in the right directory"""
        build_type = self.cfg["build_type"]
        run_cmd("mkdir -p ../bin ; pwd; cp lmp_%s ../bin" % build_type)
        run_cmd("ln -s lmp_%s ../bin/lmp" % build_type)
        run_cmd("cp list-packages.txt ..")
        if self.cfg["build_static_libs"] or self.cfg["build_shared_libs"]: 
            run_cmd("mkdir -p ../lib; cp liblammps* ../lib")

    # Perform sanity check:

    def sanity_check_step(self):
        """Custom sanity check for LAMMPS."""
        build_type = self.cfg["build_type"]
        custom_paths = {
              'files': ['README', 'LICENSE', 'list-packages.txt','bin/lmp_%s' % build_type ],
              'dirs': ['bin', 'lib', 'examples', 'potentials'],
        }
        super(EB_LAMMPS, self).sanity_check_step(custom_paths=custom_paths)

# End of the EasyBlock for LAMMPS.
