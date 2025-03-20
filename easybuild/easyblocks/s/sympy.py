##
# Copyright 2009-2025 Ghent University
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
@author: Kenneth Hoste (HPC-UGent)
"""

import os
import tempfile

from easybuild.easyblocks.generic.pythonpackage import PythonPackage, det_pylibdir


class EB_sympy(PythonPackage):
    """Custom easyblock for installing the sympy Python package."""

    def test_step(self):
        """Custom test step for sympy"""

        self.cfg['runtest'] = "python setup.py test"

        # we need to make sure that the temporary directory being used is not a symlinked path;
        # see https://github.com/easybuilders/easybuild-easyconfigs/issues/17593
        original_tmpdir = tempfile.gettempdir()
        tempfile.tempdir = os.path.realpath(tempfile.gettempdir())
        msg = "Temporary directory set to resolved path %s (was %s), " % (original_tmpdir, tempfile.gettempdir())
        msg += "to avoid failing tests due to the temporary directory being a symlinked path..."
        self.log.info(msg)

        super(EB_sympy, self).test_step(self)

        # restore original temporary directory
        tempfile.tempdir = original_tmpdir
        self.log.debug("Temporary directory restored to %s", tempfile.gettempdir())

    def sanity_check_step(self, *args, **kwargs):
        """Custom sanity check for sympy."""

        # can't use self.pylibdir here, need to determine path on the fly using currently active 'python' command;
        # this is important for sympy installations for multiple Python version (via multi_deps)
        custom_paths = {
            'files': [os.path.join('bin', 'isympy')],
            'dirs': [os.path.join(det_pylibdir(), 'sympy')],
        }

        custom_commands = ["isympy --help"]

        return super(EB_sympy, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
