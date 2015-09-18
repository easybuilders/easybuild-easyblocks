##
# Copyright 2015 Fokko Masselink
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
EasyBuild support for building and installing QtCreator, implemented as an easyblock

@author: Fokko Masselink
"""
import os
import re
import sys
import fileinput
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.run import run_cmd
from easybuild.tools.filetools import mkdir 
import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain


from easybuild.easyblocks.generic.configuremake import ConfigureMake
class EB_QTCREATOR(ConfigureMake):
    """Support for building/installing QtCreator."""

    def configure_step(self): 
        """Adjust configure step"""

        # create separate build directory
        sep_builddir = 'qt-creator-build'
        try:
            os.mkdir(sep_builddir)
            os.chdir(sep_builddir)
        except OSError, err:
            self.log.error("Failed to create separate build dir %s in %s: %s" % (objdir, os.getcwd(), err))

        cmd = "qmake -r ../qtcreator.pro" 
        run_cmd(cmd, log_all=True, simple=True)

        # update installopts
        self.cfg.update('installopts', 'INSTALL_ROOT=%s' % ( self.installdir ))

    def sanity_check_step(self):
        custom_paths = {
            'files': ["bin/qtcreator", "bin/qbs"],
            'dirs':  ["lib"],
        }
        super(EB_QTCREATOR, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        txt = super(EB_QTCREATOR, self).make_module_extra()
        txt += self.module_generator.prepend_paths("PATH", ['bin'])
        txt += self.module_generator.prepend_paths("LD_LIBRARY_PATH", ['lib'])
        return txt 
