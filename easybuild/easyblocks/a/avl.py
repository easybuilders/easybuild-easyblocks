##
# Copyright 2009-2018 Ghent University
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
EasyBuild support for installing AVL, implemented as an easyblock
Shamelessly ripped off from the ANSYS and MATLAB easyblocks.

@author: Kenneth Hoste (Ghent University)
@author: Bart Verleye (Centre for eResearch, Auckland)
@author: Chris Samuel (Swinburne University of Technology, Melbourne, Australia)
"""
import os
import stat
from distutils.version import LooseVersion

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.tools.run import run_cmd
from easybuild.tools.filetools import adjust_permissions, write_file


class EB_AVL(PackedBinary):
    """Support for installing AVL."""

    def __init__(self, *args, **kwargs):
        """Initialize AVL-specific variables."""
        super(EB_AVL, self).__init__(*args, **kwargs)
        self.avlver = "v%s" % ''.join(self.version.split('.')[0:2])

    def install_step(self):
        """Custom install procedure for AVL."""
        licserv = self.cfg['license_server']
        if licserv is None:
            licserv = os.getenv('EB_AVL_LICENSE_SERVER', 'license.example.com')
        licport = self.cfg['license_server_port']
        if licport is None:
            licport = os.getenv('EB_AVL_LICENSE_SERVER_PORT', '27012')

        cmd = "./setup.sh --mode unattended --prefix %s " % (os.path.join(self.installdir,self.avlver))
        run_cmd(cmd, log_all=True, simple=True)

        # create license file
        lictxt = '\n'.join([
            "SERVER %s 000000000000 %s" % (licserv, licport),
            "USE_SERVER",
        ])

        licfile = os.path.join(self.installdir, self.avlver, 'etc/lmx/license.dat')
        write_file(licfile, lictxt)

        adjust_permissions(self.installdir, stat.S_IWOTH, add=False)

    def make_module_req_guess(self):
        """Custom extra module file entries for AVL."""
        guesses = super(EB_AVL, self).make_module_req_guess()
        dirs = [
            "bin",
#            "AUTOSHAFT/bin",
#            "AWS/bin",
#            "BOOST/bin",
#            "CAA/bin",
#            "CFDTOOLS/bin",
#            "CFDWM/bin",
#            "EXCITE_AC/bin",
#            "EXCITE/bin",
#            "EXCITE_PR/bin",
#            "EXCITE_TD/bin",
#            "FIRE/bin",
#            "IMPRESS/bin",
#            "TABKIN/bin",
        ]
        guesses.update({"PATH": [os.path.join(self.avlver, dir) for dir in dirs]})
        return guesses

    def make_module_extra(self):
        """Define extra environment variables required by AVL"""
        txt = super(EB_AVL, self).make_module_extra()
        return txt

    def sanity_check_step(self):
        """Custom sanity check for AVL."""
        custom_paths = {
           'files': [os.path.join(self.avlver, x) for x in ['FIRE/bin/fire_launcher.py', 'bin/fire_wm', 'bin/diagnose']],
           'dirs': [os.path.join(self.avlver, x) for x in ["bin", "FIRE", "resource","tools"]]
        }
        super(EB_AVL, self).sanity_check_step(custom_paths=custom_paths)
