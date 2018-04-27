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

from easybuild.easyblocks.generic.pythonpackage import det_pylibdir
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import change_dir, copy_file, mkdir, symlink
from easybuild.tools.modules import get_software_libdir, get_software_root, get_software_version
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


BUILD_TYPE_MPI = 'mpi'


class EB_LAMMPS(EasyBlock):
    """Support for building/installing LAMMPS."""

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for LAMMPS."""
        super(EB_LAMMPS, self).__init__(*args, **kwargs)

        self.build_in_installdir = True
        self.make_vars = ''
        self.lammps_pylibdir = None

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for LAMMPS."""
        extra_vars = {
            'build_shared_libs': [True, "Build shared libraries", CUSTOM],
            'build_static_libs': [True, "Build static libraries", CUSTOM],
            'build_type': [BUILD_TYPE_MPI, "Argument passed to 'make' for building LAMMPS itself", CUSTOM],
            'lmp_inc': ['-DLAMMPS_MEMALIGN=64', "Options to include in value for LMP_INC argument to make", CUSTOM],
            'packaged_libraries': [[], "Libraries to package with LAMMPS", CUSTOM],
            'packages_no': [[], "LAMMPS packages to avoid installing", CUSTOM],
            'packages_yes': [[], "LAMMPS packages to install", CUSTOM],
        }
        return EasyBlock.extra_options(extra_vars)

    def extract_step(self):
        """Extract LAMMPS sources."""
        # strip off top-level subdirectory
        self.cfg.update('unpack_options', '--strip-components=1')
        super(EB_LAMMPS, self).extract_step()

    def configure_step(self):
        """No configure step for LAMMPS."""

        lmp_inc = 'LMP_INC'
        make_vars = {lmp_inc: self.cfg['lmp_inc']}

        # build Python bindings if Python is included as a dependency
        # this implies building shared LAMMPS library
        if get_software_root('Python'):
            self.lammps_pylibdir = det_pylibdir()
            self.cfg['build_shared_libs'] = True

        # enable FFmpeg/gzip support if included as dependency
        # having the corresponding binaries in $PATH suffices
        for dep in ['FFmpeg', 'gzip']:
            if get_software_root(dep):
                make_vars[lmp_inc] += ' -DLAMMPS_%s' % dep.upper()

        # enable FFmpeg support if included as dependency
        # specify locations of FFTW headers & libraries via FFT_INC and FFT_PATH
        fftw_root = get_software_root('FFTW')
        if fftw_root:
            fftw_majver = get_software_version('FFTW').split('.')[0]

            fftw_libdir = get_software_libdir('FFTW', only_one=True)
            if fftw_libdir is None:
                raise EasyBuildError("Failed to find FFmpeg lib subdirectory in %s", fftw_root)

            make_vars.update({
                'FFT_INC': "-DFFT_FFTW%s -I%s" % (fftw_majver, os.path.join(fftw_root, 'include')),
                'FFT_LIB': "-lfftw3",
                'FFT_PATH': "-L%s" % os.path.join(fftw_root, fftw_libdir),
            })

        # enable jpg/png support if libjpeg-turbo/libpng are included as dependency
        # specify locations of corresponding headers & libraries via JPG_INC & JPG_PATH
        for key in ['JPG_INC', 'JPG_LIB', 'JPG_PATH']:
            make_vars[key] = ''

        for lib_name, key, liblink in [('libjpeg-turbo', 'JPG', '-ljpeg'), ('libpng', 'PNG', '-lpng')]:
            lib_root = get_software_root(lib_name)

            if lib_root:
                lib_libdir = get_software_libdir(lib_name, only_one=True)
                if lib_libdir is None:
                    raise EasyBuildError("Failed to find %s lib subdirectory in %s", lib_name, lib_root)

                make_vars[lmp_inc] += ' -DLAMMPS_%s' % key
                make_vars['JPG_INC'] += ' -I%s' % os.path.join(lib_root, 'include')
                make_vars['JPG_LIB'] += ' %s' % liblink
                make_vars['JPG_PATH'] += ' -L%s' % os.path.join(lib_root, lib_libdir)

        if self.cfg['build_type'] == BUILD_TYPE_MPI:
            mpi_inc_dir, mpi_lib_dir = os.getenv('MPI_INC_DIR', ''), os.getenv('MPI_LIB_DIR', '')
            if not (mpi_inc_dir and mpi_lib_dir):
                if self.dry_run:
                    mpi_inc_dir, mpi_lib_dir = '$MPI_INC_DIR', '$MPI_LIB_DIR'
                else:
                    raise EasyBuildError("Either $MPI_INC_DIR ('%s') or $MPI_LIB_DIR ('%s'), or both, is undefined",
                                         mpi_inc_dir, mpi_lib_dir)

            make_vars['MPI_INC'] = '-I%s' % mpi_inc_dir
            make_vars['MPI_LIB'] = '-lmpi -lpthread'
            make_vars['MPI_PATH'] = '-L%s' % mpi_lib_dir

        self.make_vars = ' '.join('%s="%s"' % (key, make_vars[key]) for key in sorted(make_vars.keys()))

    def build_step(self):
        """Custom build procedure for LAMMPS."""

        cc = os.getenv('CC')
        cxx = os.getenv('CXX')
        f90 = os.getenv('F90')
        suffixes = [
            # MPI wrappers should be considered first
            'mpicc', 'mpic++',
            # active serial compilers next
            cc, cxx, f90,
            # GNU compilers as backup (in case no custom Makefile for active compiler is available)
            'gcc', 'g++', 'gfortran',
            # generic fallback
            'lammps',
            # in case there is just a Makefile without extension
            '',
        ]

        # build all packages
        libdir = os.path.join(self.start_dir, 'lib')
        for pkg_t in self.cfg['packaged_libraries']:
            makefile = None
            if type(pkg_t) is tuple:
                pkg, makefile = pkg_t
            else:
                pkg = pkg_t

            pkglibdir = os.path.join(libdir, pkg)
            if os.path.exists(pkglibdir):
                self.log.info("Building %s package libraries in %s", pkg, pkglibdir)
                if not self.dry_run:  # FIXME
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

        if not self.dry_run:  # FIXME
            change_dir(os.path.join(self.start_dir, 'src'))

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

        # put together options for make command
        cmd_opts = {
            'build_type': self.cfg['build_type'],
            'buildopts': self.cfg['buildopts'],
            'make_vars': self.make_vars,
            'par': '',
            'prebuildopts': self.cfg['prebuildopts'],
        }
        if self.cfg['parallel']:
            cmd_opts['par'] = '-j %s' % self.cfg['parallel']

        # run main make commands
        make_modes = [
            ('', True),  # LAMMPS itself
            ('mode=shlib', self.cfg['build_shared_libs']),  # shared libraries
            ('mode=lib', self.cfg['build_static_libs']),  # static libraries
        ]
        for mode, enable in make_modes:
            if enable:
                cmd_opts['mode'] = mode
                cmd = "%(prebuildopts)s make %(par)s %(mode)s %(build_type)s %(make_vars)s %(buildopts)s" % cmd_opts
                run_cmd(cmd, log_all=True)

    def install_step(self):
        """Copying files in the right directory"""

        # copy binary and symlink bin/lmp to it
        lmp_bin = 'lmp_%s' % self.cfg['build_type']
        bin_dir = os.path.join(self.installdir, 'bin')
        copy_file(os.path.join(self.start_dir, 'src', lmp_bin), os.path.join(bin_dir, lmp_bin))
        symlink(os.path.join(bin_dir, lmp_bin), os.path.join(bin_dir, 'lmp'))

        # copy libraries to standard location <prefix>/lib
        for lib in glob.glob('liblammps*'):
            copy_file(lib, os.path.join(self.installdir, 'lib', lib))

        # install Python bindings
        if self.lammps_pylibdir:
            change_dir(os.path.join(self.start_dir, 'python'))
            pylibdir = os.path.join(self.installdir, self.lammps_pylibdir)
            mkdir(pylibdir, parents=True)
            cmd = "python install.py %s" % pylibdir
            run_cmd(cmd, log_all=True)

        # FIXME?
        copy_file('list-packages.txt', os.path.join(self.installdir, 'list-packages.txt'))

    def sanity_check_step(self):
        """Custom sanity check for LAMMPS."""

        build_type = self.cfg['build_type']

        files = ['bin/lmp', 'bin/lmp_%s' % build_type]
        custom_commands = []

        if self.cfg['build_shared_libs']:
            shlib_ext = get_shared_lib_ext()
            files.extend(['lib/liblammps.%s' % shlib_ext, 'lib/liblammps_%s.%s' % (build_type, shlib_ext)])

        if self.cfg['build_static_libs']:
            files.extend(['lib/liblammps.a', 'lib/liblammps_%s.a' % build_type])

        if self.lammps_pylibdir:
            files.append(os.path.join(self.lammps_pylibdir, 'lammps.py'))
            custom_commands.append("python -c 'from lammps import lammps; lmp = lammps()'")

        custom_paths = {
            'files': files,
            'dirs': ['bench', 'doc', 'examples', 'lib', 'potentials', 'python', 'tools'],
        }
        super(EB_LAMMPS, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self):
        """Also update $PYTHONPATH if LAMMPS Python bindings are being installed."""
        txt = super(EB_LAMMPS, self).make_module_extra()

        if self.lammps_pylibdir:
            txt += self.module_generator.prepend_paths('PYTHONPATH', self.lammps_pylibdir)

        return txt
