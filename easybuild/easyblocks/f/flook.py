##
# Copyright 2023 Utrecht University
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
EasyBuild support for building and installing flook, implemented as an easyblock

@author: Arnold Kole (Utrecht University)
"""

from easybuild.easyblocks.generic.configuremake import ConfigureMake


class EB_flook(ConfigureMake):
    """Support for building/installing flook."""

    def __init__(self, *args, **kwargs):
        # call out to original constructor first, so 'self' (i.e. the class instance) is initialised
        super(EB_flook, self).__init__(*args, **kwargs)

        # Set some default options
        local_comp_flags = 'VENDOR="gnu" FFLAGS="$FFLAGS" CFLAGS="$CFLAGS"'
        self.cfg.update('buildopts', 'liball %s' % local_comp_flags)
        self.cfg.update('parallel', 1)

    def configure_step(self):
        # flook has no configure step
        pass

    def install_step(self):
        self.cfg.update('install_cmd', 'PREFIX=%s' % self.installdir)
        super(EB_flook, self).install_step()

    def sanity_check_step(self):
        custom_paths = {
            'files': ['include/flook.mod', 'lib/libflook.a', 'lib/libflookall.a', 'lib/pkgconfig/flook.pc'],
            'dirs': [],
        }

        # call out to parent to do the actual sanity checking, pass through custom paths
        super(EB_flook, self).sanity_check_step(custom_paths=custom_paths)
