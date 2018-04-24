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
"""
import glob
import os

from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import MANDATORY
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import change_dir, copy_file, symlink
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
            'build_shared_libs': [True, "Build shared libraries", CUSTOM],
            'build_static_libs': [True, "Build static libraries", CUSTOM],
            'build_type': ['', 'Argument passed to "make" for building LAMMPS itself', CUSTOM],
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
            # in case there is just a Makefile without extension
            ''
        ]

        # build all packages
        for pkg_t in self.cfg['packaged_libraries']:
            makefile = None
            if type(pkg_t) is tuple:
                pkg, makefile = pkg_t
            else:
                pkg = pkg_t

            pkglibdir = os.path.join(libdir, pkg)
            if os.path.exists(pkglibdir):
                self.log.info("Building %s package libraries in %s", pkg, pkglibdir)
                change_dir(pkglibdir)

                if makefile is None:
                    for suffix in suffixes:
                        pot_makefile = 'Makefile'
                        if suffix:
                            pot_makefile += '.%s' % suffix

                        self.log.debug("Checking for %s in %s", pot_makefile, pkglibdir)
                        if os.path.exists(pot_makefile):
                            makefile = pot_makefile
                            self.log.debug("Found %s in %s", makefile, pkglibdir)
                            break

                if makefile is None:
                    raise EasyBuildError("No makefile matching active compilers found in %s", pkglibdir)

                # make sure active compiler is used
                run_cmd('make -f %s CC="%s" CXX="%s" FC="%s" F90="%s"' % (makefile, cc, cxx, f90, f90), log_all=True)

            change_dir(srcdir)

        for pkg in self.cfg['packages_yes']:
            self.log.info("Building %s package", pkg)
            run_cmd("make yes-%s" % pkg, log_all=True)

        for pkg in self.cfg['packages_no']:
            self.log.info("Not building %s package", pkg)
            run_cmd("make no-%s" % pkg, log_all=True)

        # save the list of built packages
        run_cmd("echo Supported Packages: > list-packages.txt")
        run_cmd("make package-status | grep -a 'YES:' >> list-packages.txt")
        run_cmd("echo Not Supported Packages: >> list-packages.txt")
        run_cmd("make package-status | grep -a 'NO:' >> list-packages.txt")
        run_cmd("make package-update")

        # build LAMMPS itself
        build_type = self.cfg['build_type']
        run_cmd("make %s" % build_type, log_all=True)

        # build shared libraries
        if self.cfg["build_shared_libs"]:
            run_cmd("make mode=shlib %s" % build_type, log_all=True)

        # build static libraries
        if self.cfg["build_static_libs"]:
            run_cmd("make mode=lib %s" % build_type, log_all=True)

    def install_step(self):
        """Copying files in the right directory"""
        lmp_bin = 'lmp_%s' % self.cfg['build_type']
        bin_dir = os.path.join(self.installdir, 'bin')
        copy_file(lmp_bin, os.path.join(bin_dir, lmp_bin))
        symlink(os.path.join(bin_dir, lmp_bin), os.path.join(bin_dir, 'lmp'))
        for lib in glob.glob('liblammps*'):
            copy_file(lib, os.path.join(self.installdir, 'lib', lib))
        copy_file('list-packages.txt', os.path.join(self.installdir, 'list-packages.txt'))

    def sanity_check_step(self):
        """Custom sanity check for LAMMPS."""
        build_type = self.cfg['build_type']
        custom_paths = {
            'files': ['src/list-packages.txt', 'list-packages.txt', 'bin/lmp_%s' % build_type, 'bin/lmp'],
            'dirs': ['lib'],
        }
        super(EB_LAMMPS, self).sanity_check_step(custom_paths=custom_paths)
