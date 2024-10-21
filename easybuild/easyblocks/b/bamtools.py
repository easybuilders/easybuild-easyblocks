##
# Copyright 2009-2024 The Cyprus Institute
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
EasyBuild support for BamTools, implemented as an easyblock

@author: Andreas Panteli (The Cyprus Institute)
@author: Kenneth Hoste (Ghent University)
"""
from easybuild.tools import LooseVersion
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.generic.makecp import MakeCp
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_BamTools(MakeCp, CMakeMake):
    """Support for building and installing BamTools."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters for BamTools."""
        extra_vars = MakeCp.extra_options()
        extra_vars.update(CMakeMake.extra_options())

        # files_to_copy is not mandatory here, since we overwrite it in install_step
        extra_vars['files_to_copy'][2] = CUSTOM
        # BamTools requires an out of source build
        extra_vars['separate_build_dir'][0] = True

        return extra_vars

    def configure_step(self):
        """Configure BamTools build."""
        CMakeMake.configure_step(self)

    def install_step(self):
        """Custom installation procedure for BamTools."""
        if LooseVersion(self.version) < LooseVersion('2.5.0'):
            self.cfg['files_to_copy'] = ['bin', 'lib', 'include', 'docs', 'LICENSE', 'README']
            MakeCp.install_step(self)
        else:
            CMakeMake.install_step(self)

    def sanity_check_step(self):
        """Custom sanity check for BamTools."""

        shlib_ext = get_shared_lib_ext()

        custom_paths = {
            'files': ['bin/bamtools'],
            'dirs': [],
        }
        if LooseVersion(self.version) < LooseVersion('2.3.0'):
            # bamtools-utils & jsoncpp libs now built as static libs by default since v2.3.0
            custom_paths['files'].extend(['lib/libbamtools-utils.%s' % shlib_ext, 'lib/libjsoncpp.%s' % shlib_ext])
        elif LooseVersion(self.version) < LooseVersion('2.5.0'):
            custom_paths['files'].extend(['include/shared/bamtools_global.h', 'lib/libbamtools.a',
                                          'lib/libbamtools.%s' % shlib_ext, 'lib/libbamtools-utils.a',
                                          'lib/libjsoncpp.a'])
            custom_paths['dirs'].extend(['include/api', 'docs'])
        else:
            custom_paths['files'].extend(['include/bamtools/shared/bamtools_global.h',
                                          ('lib/libbamtools.a', 'lib64/libbamtools.a')])
            custom_paths['dirs'].extend(['include/bamtools/api', ('lib/pkgconfig', 'lib64/pkgconfig')])

        super(EB_BamTools, self).sanity_check_step(custom_paths=custom_paths)
