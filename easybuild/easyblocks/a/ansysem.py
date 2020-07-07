##
# Copyright 2009-2020 Ghent University
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
EasyBuild support for installing ANSYS Eletromagnetics

@author: Alexi Rivera (Chalmers University of Technology)
@author: Mikael OEhman (Chalmers University of Technology)
"""
import os
import glob

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.run import run_cmd


class EB_ANSYSEM(PackedBinary):
    """Support for installing Ansys Electromagnetics."""

    def __init__(self, *args, **kwargs):
        """Initialize Ansys Electromagnetics specific variables."""
        super(EB_ANSYSEM, self).__init__(*args, **kwargs)
        self.replayfile = None

    def configure_step(self):
        """Configure Ansys Electromagnetics installation."""
        licserv = os.getenv('EB_ANSYS_EM_LICENSE_SERVER')
        licport = os.getenv('EB_ANSYS_EM_LICENSE_SERVER_PORT')
        licservers = ['', '', '']
        for i, licserver in licserv.split(','):
            licservers[i] = licserver
        try:
            self.replayfile = os.path.join(self.builddir, "installer.properties")
            txt = '\n'.join([
                "-W Agree.selection=1",
                "-P installLocation=\"%s\"" % self.installdir,
                "-W TempDirectory.tempPath=\"/tmp\"",
                "-W TempDirectory.ChangeTempPermission=\"0\"",
                "-W LibraryOption.libraryOption=0",
                "-W LibraryOption.libraryPath=\"\"",
                "-W LicenseOption.licenseOption=2",
                "-W LicenseOption.licenseFileName=\"\"",
                "-W LicenseOption.serverCount=%s" % servercount,
                "-W LicenseOption.serverName1=\"%s\"" % licservers[0],
                "-W LicenseOption.serverName2=\"%s\"" % licservers[1],
                "-W LicenseOption.serverName3=\"%s\"" % licservers[2],
                "-W LicenseOption.tcpPort=%s" % licport,
            ])
            with file(self.replayfile, "w") as f:
                f.write(txt)
        except IOError as err:
            raise EasyBuildError("Failed to create install properties file used for replaying installation: %s", err)

    def install_step(self):
        """Install Ansys Electromagnetics using its setup tool."""
        cmd = "./Linux/AnsysEM/disk1/setup.exe -options \"%s\" -silent" % (self.replayfile)
        run_cmd(cmd, log_all=True, simple=True)

    def make_module_extra(self):
        """Extra module entries for Ansys Electromagnetics."""
        idirs = glob.glob(os.path.join(self.installdir, 'AnsysEM*/Linux*/'))
        if len(idirs) == 1:
            subdir = os.path.relpath(idirs[0], self.installdir)
        else:
            raise EasyBuildError("Failed to locate single install subdirectory AnsysEM*/Linux*/")

        txt = super(EB_ANSYSEM, self).make_module_extra()
        txt += self.module_generator.prepend_paths('PATH', subdir)
        # Not sure if these are needed;
        # txt += self.module_generator.prepend_paths('LD_LIBRARY_PATH', [os.path.join(ansysdir, 'mainwin540', 'Linux64', 'mw', 'lib-amd64_linux_optimized')])
        # txt += self.module_generator.prepend_paths('LIBRARY_PATH', [os.path.join('ansysdir', 'mainwin540', 'Linux64', 'mw', 'lib-amd64_linux_optimized')])
        return txt

    def sanity_check_step(self):
        """Custom sanity check for Ansys Electromagnetics."""
        idirs = glob.glob(os.path.join(self.installdir, 'AnsysEM*/Linux*/'))
        if len(idirs) == 1:
            subdir = os.path.relpath(idirs[0], self.installdir)
        else:
            raise EasyBuildError("Failed to locate single install subdirectory AnsysEM*/Linux*/")

        custom_paths = {
            'files': [os.path.join(subdir, 'ansysedt')],
            'dirs': [subdir],
        }
        super(EB_ANSYSEM, self).sanity_check_step(custom_paths=custom_paths)
