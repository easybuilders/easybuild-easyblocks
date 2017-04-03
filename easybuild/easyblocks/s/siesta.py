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
import shutil
import easybuild.tools.toolchain as toolchain
from easybuild.tools.run import run_cmd
from distutils.version import LooseVersion
from easybuild.framework.easyconfig import CUSTOM
from easybuild.easyblocks.generic.makecp import MakeCp
from easybuild.tools.filetools import apply_regex_substitutions


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
            cfg_cmd += "%(configopts)s" % {
            'configopts': self.cfg['configopts'],
}


        try:
            os.chdir('Obj')
        except OSError, err:
            raise EasyBuildError("Failed to move into build dir: %s", err)

        run_cmd(cfg_cmd, log_all=True, simple=True, log_output=True)

        # make sure packaged lapack is not on generated arch.make
        apply_regex_substitutions('arch.make', [('dc_lapack.a', ''), ('libsiestaLAPACK.a', '')])

        if self.cfg['with_transiesta']:
            try:
                shutil.copytree('../Obj', '../Obj2')
            except OSError, err:
                raise EasyBuildError("Failed to copy build dir: %s", err)

        run_cmd("make", log_all=True, simple=True, log_output=True)

        if self.cfg['with_transiesta']:
            try:
                os.chdir('../Obj2')
            except OSError, err:
                raise EasyBuildError("Failed to move to transiesta build dir: %s", err)
            run_cmd("make transiesta", log_all=True, simple=True, log_output=True)

        if self.cfg['with_utils']:
            try:
                os.chdir('../Util')
            except OSError, err:
                raise EasyBuildError("Failed to move to Util dir: %s", err)
            run_cmd("./build_all.sh", log_all=True, simple=True, log_output=True)

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
