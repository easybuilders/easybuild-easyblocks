##
# Copyright 2013 the Cyprus Institute
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
@author: Maxime Boissonneault (Compute Canada, Calcul Quebec, Universite Laval)
"""
import os
import shutil
import glob

from easybuild.easyblocks.generic.makecp import MakeCp
from easybuild.framework.easyconfig import BUILD, MANDATORY
from easybuild.tools.run import run_cmd
from easybuild.tools.build_log import EasyBuildError


class EB_deMon2k(MakeCp):
    """
    Software with no configure and no make install step.
    """
    @staticmethod
    def extra_options(extra_vars=None):
        """
        Define list of files or directories to be copied after make
        """
        extra = {
            'files_to_copy': [[], "List of files or dirs to copy", MANDATORY],
        }
        if extra_vars is None:
            extra_vars = {}
        extra.update(extra_vars)
        return MakeCp.extra_options(extra_vars=extra)

    def build_step(self, verbose=False, path=None):
        """
        Start the actual build
        """
        os.environ['CREX_ROOT'] = os.path.join(self.cfg['start_dir'],"..")
        cmd = "%s ./CREX %s " % (self.cfg['prebuildopts'], self.cfg['buildopts'])

        (out, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)

        return out

