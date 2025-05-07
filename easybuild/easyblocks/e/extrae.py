##
# Copyright 2009-2025 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# the Hercules foundation (http://www.herculesstichting.be/in_English)
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
EasyBuild support for building and installing Extrae, implemented as an easyblock

@author Bernd Mohr (Juelich Supercomputing Centre)
"""

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.modules import get_software_root
from easybuild.tools import LooseVersion
from easybuild.tools.systemtools import RISCV64
from easybuild.tools.systemtools import get_cpu_architecture


class EB_Extrae(ConfigureMake):
    """Support for building/installing Extrae."""

    def configure_step(self):
        """Configure Extrae build, set configure options for compiler, MPI and dependencies."""

        # MPI
        self.cfg.update('configopts', "--with-mpi=%s" % get_software_root(self.toolchain.MPI_MODULE_NAME[0]))

        # Optional dependences
        # Both --enable-xml and --with-dwarf options are no longer available from 4.1.0 version
        # Instead, --with-xml is used
        if LooseVersion(self.version) >= LooseVersion('4.1.0'):
            deps = {
                'binutils': ('', '--with-binutils=%s', ''),
                'Boost': ('', '--with-boost=%s', ''),
                'libunwind': ('', '--with-unwind=%s', '--without-unwind'),
                'libxml2': ('--enable-merge-in-trace', '--with-xml=%s', ''),
                'PAPI': ('--enable-sampling', '--with-papi=%s', '--without-papi'),
                'zlib': ('', '--with-libz=%s', ''),
            }
        else:
            deps = {
                'binutils': ('', '--with-binutils=%s', ''),
                'Boost': ('', '--with-boost=%s', ''),
                'libdwarf': ('', '--with-dwarf=%s', '--without-dwarf'),
                'libunwind': ('', '--with-unwind=%s', '--without-unwind'),
                'libxml2': (' --enable-xml --enable-merge-in-trace', '', ''),
                'PAPI': ('--enable-sampling', '--with-papi=%s', '--without-papi'),
            }

        for (dep_name, (with_opts, with_root_opt, without_opt)) in deps.items():
            dep_root = get_software_root(dep_name)
            if dep_root:
                if with_opts:
                    self.cfg.update('configopts', with_opts)
                if with_root_opt:
                    self.cfg.update('configopts', with_root_opt % dep_root)
            else:
                if without_opt:
                    self.cfg.update('configopts', without_opt)

        # TODO: make this optional dependencies
        self.cfg.update('configopts', "--without-dyninst")

        # Needed to build in RISC-V architectures
        if get_cpu_architecture() == RISCV64:
            self.cfg.update('configopts', "--enable-posix-clock")

        super(EB_Extrae, self).configure_step()

    def sanity_check_step(self):
        """Custom sanity check for Extrae."""
        custom_paths = {
            'files': ['bin/mpi2prv', 'include/extrae_user_events.h', ('lib/libmpitrace.a', 'lib64/libmpitrace.a')],
            'dirs': [],
        }
        super(EB_Extrae, self).sanity_check_step(custom_paths=custom_paths)
