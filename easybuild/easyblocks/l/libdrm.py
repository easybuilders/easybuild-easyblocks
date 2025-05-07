##
# Copyright 2013-2025 Ghent University
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
EasyBuild support for building and installing libdrm, implemented as an easyblock

@author: Andrew Edmondson (University of Birmingham)
"""

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.systemtools import X86_64, get_cpu_architecture, get_shared_lib_ext


class EB_libdrm(ConfigureMake):
    """
    Support for building libdrm on different architectures
    """

    def sanity_check_step(self):
        """Custom sanity check for libdrm"""
        shlib_ext = get_shared_lib_ext()
        custom_paths = {
            'files': ['include/xf86drm.h', 'include/xf86drmMode.h',
                      'lib/libdrm_radeon.%s' % shlib_ext, 'lib/libdrm.%s' % shlib_ext, 'lib/libkms.%s' % shlib_ext],
            'dirs': ['include/libdrm', 'include/libkms', 'lib/pkgconfig'],
        }

        arch = get_cpu_architecture()
        if arch == X86_64:
            custom_paths['files'].append('lib/libdrm_intel.%s' % shlib_ext)

        super(EB_libdrm, self).sanity_check_step(custom_paths=custom_paths)
