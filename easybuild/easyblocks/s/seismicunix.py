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
EasyBuild support for building and installing SeismicUnix, implemented as an easyblock

@author: Fokko Masselink
"""
import easybuild.tools.environment as env
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.run import run_cmd
import os
import fileinput
import re
import sys

class EB_SeismicUnix(EasyBlock):
    """Support for building/installing SeismicUnix."""

    def configure_step(self):
        """
        Configure SeismicUnix. 
        """
        cmd = "cp configs/Makefile.config_Linux_x86_64 Makefile.config;"
        run_cmd(cmd, log_all=True, simple=True)
        # fix libtool for empty -l options
        # only seems to happen when building for MPI and with shared libraries
        for line in fileinput.input('Makefile.config', inplace=1, backup='.orig'):
            line = re.sub(r"^XDRFLAG\s+=.*", "XDRFLAG =", line)
            sys.stdout.write(line)

    def build_step(self):
        """
        Build SeismicUnix.
        """
        # set to one directory above 'src' dir
        env.setvar('CWPROOT', os.path.dirname(os.path.normpath(self.cfg['start_dir'])))
        cmd = "make install"
        run_cmd(cmd, log_all=True, simple=True)
        cmd = "make xtinstall"
        run_cmd(cmd, log_all=True, simple=True)

    def install_step(self):
        """
        Install SeismicUnix.
        """
        cmd = "cp -pr $CWPROOT/* %s/" % self.installdir
        run_cmd(cmd, log_all=True, simple=True)

    def sanity_check_step(self):
        """Custom sanity check for SeismicUnix."""

        binaries = ['suname']
        libs = ['libsu.a', 'libcomp.a']

        custom_paths = {
            'files':["bin/%s" % x for x in binaries] +
                    ["lib/%s" % x for x in libs],
            'dirs':[],
        }
        super(EB_SeismicUnix, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Set CWPROOT environment variable in module."""

        txt = super(EB_SeismicUnix, self).make_module_extra()

        txt += self.module_generator.set_environment('CWPROOT', self.installdir)

        return txt


