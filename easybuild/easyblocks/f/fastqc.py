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
EasyBlock for FastQC adapted from Packed Binary

@author: Jens Timmerman (Ghent University)
@author: Andreas Panteli (The Cyprus Institute)

"""
import os
import shutil

from easybuild.easyblocks.generic.binary import Binary
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.filetools import rmtree2

class EB_FastQC(Binary):
    """Support for installing packed binary software.
    Just unpack the sources in the install dir and change mod 0755 fastqc
    """

    def extract_step(self):
        """Unpack the source"""
	EasyBlock.extract_step(self)

    def install_step(self):
        """Copy all files in build directory to the install directory"""
        if self.cfg['install_cmd'] is None:
            try:
                # shutil.copytree doesn't allow the target directory to exist already
                rmtree2(self.installdir)
                shutil.copytree(self.cfg['start_dir'], self.installdir)
            except OSError, err:
                self.log.error("Failed to copy %s to %s: %s" % (self.cfg['start_dir'], self.installdir))
        else:
            self.log.info("Installing %s using command '%s'..." % (self.name, self.cfg['install_cmd']))
            run_cmd(self.cfg['install_cmd'], log_all=True, simple=True)
	#Change mod 755 fastqc
	try:
            dst = os.path.join(self.installdir, 'fastqc')
            os.chmod(dst, 0755)
	except OSError, err:
	    self.log.error("Failed to chmod fastqc in the install directory: %s" % err)
