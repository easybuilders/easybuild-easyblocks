##
# Copyright 2009-2023 Ghent University
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
EasyBuild support for sympy, implemented as an easyblock

@author: Caspar van Leeuwen (SURF)
"""

import os
import tempfile

from easybuild.easyblocks.generic.pythonpackage import PythonPackage


class EB_sympy(PythonPackage):
    """Build sympy"""

    def test_step(self):
        """Test step for sympy"""
        original_tmpdir = tempfile.gettempdir()
        tempfile.tempdir = os.path.realpath(tempfile.gettempdir())
        self.log.debug("Changing TMPDIR for test step to avoid easybuild-easyconfigs issue #17593.")
        self.log.debug("Old TMPDIR %s. New TMPDIR %s.", original_tmpdir, tempfile.gettempdir())
        super(EB_sympy, self).test_step(self)
        tempfile.tempdir = original_tmpdir
        self.log.debug("Restored TMPDIR to %s", tempfile.gettempdir())
