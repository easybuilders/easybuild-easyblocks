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
EasyBuild support for Ansys Electromagnetics, implemented as an easyblock
@author: Alexi Rivera (Chalmers University of Technology)
"""
import os
import re

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.run import run_cmd
from easybuild.framework.easyconfig import CUSTOM


class EB_ANSYSEM(PackedBinary):
    """Support for installing Ansys Electromagnetics."""

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for Ansys Electromagnetics."""
        super(EB_ANSYSEM, self).__init__(*args, **kwargs)
        self.replayfile = None
        if self.cfg['internal_version']:
            self.internal_version = self.cfg['internal_version']
        else:
            # Generate internal-version from user-facing version if no override specified
            self.internal_version = re.sub(r'\d{2}(\d{2})R(\d)', r'\1.\2', self.version, 0)

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for ANSYS EM"""
        extra_vars = {
            'ansysem_temp_dir': [
                None,
                "Select a default location for all simulations (including local) to use as a temporary work space.",
                CUSTOM
            ],
            'internal_version': [
                None,
                "Override the version number that ANSYS EM uses internally, e.g. '20.1' for '2020R1'.",
                CUSTOM
            ],
            'update_version': [
                None,
                "Version number of the update to apply. Requires the update zip file in the list of sources.",
                CUSTOM
            ],
        }
        return PackedBinary.extra_options(extra_vars)

    def configure_step(self):
        """Configure Ansys Electromagnetics installation."""
        licserv = self.cfg['license_server']
        if licserv is None:
            licserv = os.getenv('EB_ANSYS_EM_LICENSE_SERVER')
        licport = self.cfg['license_server_port']
        if licport is None:
            licport = os.getenv('EB_ANSYS_EM_LICENSE_SERVER_PORT')
        if not licserv:
            raise EasyBuildError("Please ensure that a license server is specified \
either in the Easyconfig or as the env var EB_ANSYS_EM_LICENSE_SERVER")
        if not licport:
            raise EasyBuildError("Please ensure that a license server port is specified \
either in the Easyconfig or as the env var EB_ANSYS_EM_LICENSE_SERVER_PORT")
        licserver = licserv.split(',')
        servercount = len(licserver)
        for _ in range(servercount, 3):
            licserver.append("")
        tmpdir = self.cfg['ansysem_temp_dir']
        if tmpdir is None:
            tmpdir = "/tmp"
        try:
            self.replayfile = os.path.join(self.builddir, "installer_properties.iss")
            txt = '\n'.join([
                "-W Agree.selection=1",
                "-P installLocation=\"%s\"" % self.installdir,
                "-W TempDirectory.tempPath=\"%s\"" % tmpdir,
                "-W TempDirectory.ChangeTempPermission=\"0\"",
                "-W LibraryOption.libraryOption=0",
                "-W LibraryOption.libraryPath=\"\"",
                "-W LicenseOption.licenseOption=2",
                "-W LicenseOption.licenseFileName=\"\"",
                "-W LicenseOption.serverCount=%s" % servercount,
                "-W LicenseOption.serverName1=\"%s\"" % licserver[0],
                "-W LicenseOption.serverName2=\"%s\"" % licserver[1],
                "-W LicenseOption.serverName3=\"%s\"" % licserver[2],
                "-W LicenseOption.tcpPort=%s" % licport,
            ])
            with open(self.replayfile, "w") as f:
                f.write(txt)
        except IOError as err:
            raise EasyBuildError("Failed to create install properties file used for replaying installation: %s", err)

    def install_step(self):
        """Install Ansys Electromagnetics using 'install'."""
        cmd = "./Linux/AnsysEM/disk1/setup.exe -options \"%s\" -silent" % (self.replayfile)
        run_cmd(cmd, log_all=True, simple=True)

        # Run the update, if the extra variable is provided
        if self.cfg['update_version']:
            int_update_ver = re.sub(r'^\d{2}(\d{2})R(.+)$', r'\1.\2', self.cfg['update_version'], 0)
            update_filepath = "%s/Electronics_%s_linx64" % (self.builddir, int_update_ver)
            cmd = '%s/install_patch.bash --install_dir %s' % (update_filepath, self.installdir)
            (out, _) = run_cmd(cmd, simple=False, log_all=False, log_ok=False)
            self.log.debug("Output from update:\n\n%s" % out)
            # Search for "Patch installed successfully" in the output text
            if not re.search("Patch installed successfully", out) and not self.dry_run:
                raise EasyBuildError("ANSYSEM update failed with output:\n\n%s" % out)

    def make_module_extra(self):
        """Extra module entries for Ansys Electromagnetics."""
        txt = super(EB_ANSYSEM, self).make_module_extra()
        txt += self.module_generator.prepend_paths(
            'PATH', ['AnsysEM%s/Linux64' % self.internal_version]
            )
        txt += self.module_generator.prepend_paths(
            'LD_LIBRARY_PATH', [
                'AnsysEM%s/Linux64/mainwin560/Linux64/mw/lib-amd64_linux_optimized' % self.internal_version
            ]
            )
        txt += self.module_generator.prepend_paths(
            'LIBRARY_PATH', [
                'AnsysEM%s/Linux64/mainwin560/Linux64/mw/lib-amd64_linux_optimized' % self.internal_version
            ]
            )
        return txt

    def sanity_check_step(self):
        """Custom sanity check for Ansys Electromagnetics."""
        custom_paths = {
            'files': [
                'AnsysEM%s/Linux64/libAnsPlot.so' % self.internal_version,
                'AnsysEM%s/Linux64/Gen3dProj' % self.internal_version,
                'AnsysEM%s/Linux64/G3dMesher' % self.internal_version,
            ],
            'dirs': ['AnsysEM%s/Linux64/mainwin560' % self.internal_version],
        }
        super(EB_ANSYSEM, self).sanity_check_step(custom_paths=custom_paths)