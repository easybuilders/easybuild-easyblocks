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
EasyBuild support for building and installing reticulate R package, implemented as an easyblock

@author: Samuel Moors (Vrije Universiteit Brussel)
"""
import os

from easybuild.easyblocks.generic.rpackage import RPackage
from easybuild.tools.modules import get_software_root


class EB_reticulate(RPackage):
    """Support for installing the reticulate R package."""

    def install_extension(self):
        """Add extra environment variables to modulefile"""

        txt = super(EB_reticulate, self).install_extension()
        if not txt:
            txt = ""

        pythonroot = get_software_root('Python')
        if pythonroot:
            # make sure EB-provided Python is used, and that reticulate does not install it's own Python
            # see: https://rstudio.github.io/reticulate/reference/use_python.html
            # see: https://github.com/rstudio/reticulate/issues/894
            txt += self.module_generator.set_environment('RETICULATE_PYTHON', os.path.join(pythonroot, 'bin', 'python'))
        else:
            self.log.info("Python not included as dependency, so RETICULATE_PYTHON not set")

        self.log.info("adding to modulefile: %s" % txt)
        return txt
