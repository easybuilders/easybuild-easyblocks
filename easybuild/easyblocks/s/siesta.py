##
# Copyright 2009-2016 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
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
EasyBuild support for Siesta, implemented as an easyblock

@author: Miguel Dias Costa (National university of Singapore)
"""

import os
import easybuild.tools.toolchain as toolchain
from distutils.version import LooseVersion
from easybuild.framework.easyconfig import CUSTOM
from easybuild.easyblocks.generic.makecp import MakeCp


class EB_Siesta(MakeCp):
    """Support for building and installing Siesta."""

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for Siesta."""
        super(EB_Siesta, self).__init__(*args, **kwargs)
        self.build_in_installdir = True

    def extract_step(self):
        """Extract sources."""
        # strip off 'siesta-<version>' part to avoid having everything in a subdirectory
        self.cfg.update('unpack_options', "--strip-components=1")
        super(EB_Siesta, self).extract_step()

    @staticmethod
    def extra_options(extra_vars=None):
        """Define extra options for Siesta."""
        extra = {
            'files_to_copy': [[], "List of files or dirs to copy", CUSTOM],
            'with_transiesta': [True, "Build transiesta", CUSTOM],
            'with_utils': [True, "Build all utils", CUSTOM],
            }
        return MakeCp.extra_options(extra_vars=extra)

    def build_step(self):
        """Custom build procedure for Siesta."""
        cfg_cmd = '../Src/obj_setup.sh && ../Src/configure'

        if self.toolchain.options.get('usempi', None):
            cfg_cmd += ' --enable-mpi '

        cfg_cmd += '--with-blas="' + os.environ['LIBBLAS'] + '" '
        cfg_cmd += '--with-lapack="' + os.environ['LIBLAPACK'] + '" '
        cfg_cmd += '--with-blacs="' + os.environ['LIBBLACS'] + '" '
        cfg_cmd += '--with-scalapack="' + os.environ['LIBSCALAPACK'] + '"'

        # make sure packaged lapack is not on generated arch.make
        sed_cmd = "sed -i 's/COMP_LIBS=dc_lapack.a/COMP_LIBS=/' arch.make"

        self.cfg.update('prebuildopts', 'cd Obj && ' + cfg_cmd + ' && ' + sed_cmd + ' && ')

        if self.cfg['with_transiesta']:
            self.cfg.update('buildopts', ' && cd .. && mkdir Obj2 && cd Obj2 && ')
            self.cfg.update('buildopts', cfg_cmd + ' && ' + sed_cmd + ' && make transiesta ')

        if self.cfg['with_utils']:
            self.cfg.update('buildopts', ' && cd ../Util && sh ./build_all.sh')

        super(EB_Siesta, self).build_step()

    def install_step(self):
        """Custom install procedure for Siesta."""

        bins = ['Obj/siesta']

        if self.cfg['with_transiesta']:
            bins.extend(['Obj2/transiesta'])

        self.cfg['files_to_copy'] = [(bins, 'bin')]

        super(EB_Siesta, self).install_step()

    def sanity_check_step(self):
        """Custom sanity check for Siesta."""

        bins = ['bin/siesta']

        if self.cfg['with_transiesta']:
            bins.extend(['bin/transiesta'])

        custom_paths = {
            'files': bins,
            'dirs': []
        }

        super(EB_Siesta, self).sanity_check_step(custom_paths=custom_paths)
