# -*- coding: utf-8 -*-
##
# Copyright 2009-2019 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
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
EasyBuild support for installing Gurobi, implemented as an easyblock

@author: Bob Dröge (University of Groningen)
"""
import os

from easybuild.easyblocks.generic.pythonpackage import det_pylibdir
from easybuild.easyblocks.generic.tarball import Tarball
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import copy_file
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd

class EB_ABAQUS(Tarball):
    """Support for installing linux64 version of Abaqus."""

    def install_step(self):

        super(EB_ABAQUS, self).install_step()

    def sanity_check_step(self):
        """Custom sanity check for ABAQUS."""
        custom_paths = {
            'files': [os.path.join('Commands', 'abaqus')],
            'dirs': [],
        }
        custom_commands = []

        super(EB_ABAQUS, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_req_guess(self):
        """Update PATH guesses for ABAQUS."""

        guesses = super(EB_ABAQUS, self).make_module_req_guess()
        guesses.update({
            'PATH': ['Commands'],
        })
        return guesses
