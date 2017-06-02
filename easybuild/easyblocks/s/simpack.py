##
# Copyright 2009-2017 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
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
EasyBuild support for installing Simpack, implemented as an easyblock

@author: Alexi Rivera (C3SE / Chalmers University of Technology)
"""

import re
import shutil
import os
import stat

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import read_file, write_file
from easybuild.tools.run import run_cmd


class EB_Simpack(PackedBinary):
    """Support for installing Simpack."""

    def __init__(self, *args, **kwargs):
        super(EB_Simpack, self).__init__(*args, **kwargs)
	self.license = self.cfg['license_server'] + ':' + self.cfg['license_server_port']
	self.defaultconf = os.path.join(self.installdir, 'defaults/settings/default.ini')

    def install_step(self):
        run_cmd("./spck-2017-build53-linux64-installer.bin --mode unattended --prefix %s" % self.installdir, log_all=True, simple=True)

    def post_install_step(self):
	if self.license != "license.example.com:000000":
	    c = open(self.defaultconf, "a")
	    print(self.defaultconf)
	    c.write('[dsls]' + '\n')
	    c.write('licServer=' + self.license + '\n')
	    c.close()

    def make_module_extra(self):
        txt = super(EB_Simpack, self).make_module_extra()
        txt += self.module_generator.prepend_paths("PATH", ['run/bin/linux64'])
        return txt

    def sanity_check_step(self):
        custom_paths = {
            'files': [],
            'dirs': ['run/bin','defaults'], 
        }
        super(EB_Simpack, self).sanity_check_step(custom_paths=custom_paths)
