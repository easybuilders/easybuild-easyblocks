##
# Copyright 2009-2013 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# the Hercules foundation (http://www.herculesstichting.be/in_English)
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
General EasyBuild support for software with a binary installer

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""

import shutil
import os
import stat

from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.filetools import run_cmd


class Binary(EasyBlock):
    """Support for installing software that comes in binary form.
    Just copy the sources to the install dir"""

    def extract_step(self):
        """Move all source files to the build directory"""

        self.src[0]['finalpath'] = self.builddir

        # copy source to build dir.
        for source in self.src:
            src = source['path']
            dst = os.path.join(self.builddir, source['name'])
            try:
                shutil.copy2(src, self.builddir)
                os.chmod(dst, stat.S_IRWXU)
            except (OSError, IOError), err:
                self.log.exception("Couldn't copy %s to %s: %s" % (src, self.builddir, err))

    def configure_step(self):
        """No configuration, this is binary software"""
        pass

    def build_step(self):
        """No compilation, this is binary software"""
        pass

    def install_step(self):
        """Copy all files in build directory to the install directory"""
        # can't use shutil.copytree because that doesn't allow the target directory to exist already
        run_cmd("cp -a %s/* %s" % (self.cfg['start_dir'], self.installdir))

    def make_module_extra(self):
        """Add the install directory to the PATH."""

        txt = super(Binary, self).make_module_extra()
        txt += self.moduleGenerator.prepend_paths("PATH", [""])
        self.log.debug("make_module_extra added this: %s" % txt)
        return txt
