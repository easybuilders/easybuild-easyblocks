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
EasyBuild support for building and installing HDF5, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""

import os

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import write_file
from easybuild.tools.modules import get_software_root
from easybuild.tools.systemtools import get_shared_lib_ext

# Pkgconfig data template
# Based on pkgconfig file from Debian packaging of HDF5
HDF5_PKG_CONFIG = """Name: HDF5
Description: Hierarchical Data Format 5 (HDF5)
Version: %s
Requires:
Cflags: -I%s
Libs: -L%s -lhdf5 %s
"""

class EB_HDF5(ConfigureMake):
    """Support for building/installing HDF5"""

    def __init__(self, *args, **kwargs):
        """Initialize HDF5-specific variables."""
        super(EB_HDF5, self).__init__(*args, **kwargs)
        # configure options for dependencies
        self.known_deps = [
            {'name': 'Szip', 'with': 'szlib', 'lib': '-lsz'},
            {'name': 'zlib', 'with': 'zlib', 'lib': '-lz'},
        ]

    def configure_step(self):
        """Configure build: set require config and make options, and run configure script."""

        for dep in self.known_deps:
            root = get_software_root(dep['name'])
            if root:
                self.cfg.update('configopts', '--with-%s=%s' % (dep['with'], root))

        fcomp = 'FC="%s"' % os.getenv('F90')

        self.cfg.update('configopts', "--with-pic --with-pthread --enable-shared")
        self.cfg.update('configopts', "--enable-cxx --enable-fortran %s" % fcomp)

        # MPI and C++ support enabled requires --enable-unsupported, because this is untested by HDF5
        # also returns False if MPI is not supported by this toolchain
        if self.toolchain.options.get('usempi', None):
            self.cfg.update('configopts', "--enable-unsupported --enable-parallel")
            mpich_mpi_families = [toolchain.INTELMPI, toolchain.MPICH, toolchain.MPICH2, toolchain.MVAPICH2]
            if self.toolchain.mpi_family() in mpich_mpi_families:
                self.cfg.update('buildopts', 'CXXFLAGS="$CXXFLAGS -DMPICH_IGNORE_CXX_SEEK"')
        else:
            self.cfg.update('configopts', "--disable-parallel")

        # make options
        self.cfg.update('buildopts', fcomp)

        # set RUNPARALLEL if MPI is not enabled (or not supported by this toolchain)
        if self.toolchain.options.get('usempi', None):
            env.setvar('RUNPARALLEL', 'mpirun -np \$\${NPROCS:=2}')

        super(EB_HDF5, self).configure_step()

    # default make and make install are ok but add a pkconfig file
    def install_step(self):
        """Custom install step for HDF5"""
        super(EB_HDF5, self).install_step()
        hdf5_lib_deps = ''
        for dep in self.known_deps:
            root = get_software_root(dep['name'])
            if root:
                hdf5_lib_deps = hdf5_lib_deps + dep['lib'] + ' '

        inc_dir = os.path.join(self.installdir, 'include')
        lib_dir = os.path.join(self.installdir, 'lib')
        hdf5_pc_txt = HDF5_PKG_CONFIG % (self.version, inc_dir, lib_dir, hdf5_lib_deps)
        write_file(os.path.join(self.installdir, "lib", "pkgconfig", "hdf5.pc"), hdf5_pc_txt)

    def sanity_check_step(self):
        """
        Custom sanity check for HDF5
        """

        # also returns False if MPI is not supported by this toolchain
        if self.toolchain.options.get('usempi', None):
            extra_binaries = ["bin/%s" % x for x in ["h5perf", "h5pcc", "h5pfc", "ph5diff"]]
        else:
            extra_binaries = ["bin/%s" % x for x in ["h5cc", "h5fc"]]

        libs = ['', '_cpp', '_fortran', '_hl_cpp', '_hl', 'hl_fortran']
        shlib_ext = get_shared_lib_ext()
        custom_paths = {
            'files': ["bin/h5%s" % x for x in ["2gif", "c++", "copy", "debug", "diff",
                                               "dump", "import", "jam","ls", "mkgrp",
                                               "perf_serial", "redeploy", "repack",
                                               "repart", "stat", "unjam"]] +
                     ["bin/gif2h5"] + extra_binaries +
                     ["lib/libhdf5%s.%s" % (l, shlib_ext) for l in libs],
            'dirs': ['include'],
        }
        super(EB_HDF5, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_req_guess(self):
        """Specify pkgconfig path for HDF5."""
        guesses = super(EB_HDF5, self).make_module_req_guess()
        guesses.update({'PKG_CONFIG_PATH': [os.path.join('lib', 'pkgconfig')]})

        return guesses

    def make_module_extra(self):
        """Also define $HDF5_DIR to installation directory."""
        txt = super(EB_HDF5, self).make_module_extra()
        txt += self.module_generator.set_environment('HDF5_DIR', self.installdir)
        return txt
