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
EasyBuild support for installing Simpack, implemented as an easyblock

@author: Alexi Rivera (Chalmers University of Technology)
@author: Mikael Oehman (Chalmers University of Technology)
"""

import os
import glob

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import write_file
from easybuild.tools.run import run_cmd


class EB_Simpack(PackedBinary):
    """Support for installing Simpack."""

    def __init__(self, *args, **kwargs):
        """Constructor for Simpack easyblock."""
        super(EB_Simpack, self).__init__(*args, **kwargs)

    def install_step(self):
        """Configure Simpack installation."""
        # Installer changes name:
        installer = glob.glob('spck-*-linux64-installer.bin')
        if len(installer) == 0:
            raise EasyBuildError("Didn't find installer")
        elif len(installer) > 1:
            raise EasyBuildError("Found to many installers: %s", installer)
        cmd = "./%s --mode unattended --prefix %s"
        run_cmd(cmd % (installer[0], self.installdir), log_all=True, simple=True)

    def post_install_step(self):
        """Post install (license configuration) for Simpack."""
        license = os.getenv('EB_SIMPACK_LICENSE_SERVER')
        if license is not None:
            defaultconf = os.path.join(self.installdir, 'defaults/settings/default.ini')
            txt = '[dsls]\nlicserver=%s\n' % license
            write_file(defaultconf, txt, append=True)

    def make_module_extra(self):
        """Extra module entries for Simpack."""
        txt = super(EB_Simpack, self).make_module_extra()
        txt += self.module_generator.prepend_paths("PATH", ['run/bin/linux64'])
        return txt

    def sanity_check_step(self):
        """Custom sanity check for Simpack."""
        custom_paths = {
            'files': ['run/bin/linux64/simpack-' + ext for ext in ['slv', 'flx', 'gui', 'post']],
            'dirs': ['run/bin/linux64', 'defaults'],
        }
        super(EB_Simpack, self).sanity_check_step(custom_paths=custom_paths)
