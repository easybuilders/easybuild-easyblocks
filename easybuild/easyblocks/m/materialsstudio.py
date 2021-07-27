##
# Copyright 2014 Ghent University
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
# along with EasyBuild. If not, see <http://www.gnu.org/licenses/>.
##
"""
@author: Maxime Boissonneault (Calcul Quebec, Compute Canada)
"""
import glob
import os
import re

from distutils.version import LooseVersion

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.run import run_cmd, run_cmd_qa


class EB_MaterialsStudio(PackedBinary):
    """Support for installing MaterialsStudio"""

    def install_step(self):
        """Build by running the command with the inputfiles"""
        license_server = os.getenv("MS_LICENSE_SERVER")
        home = os.getenv("HOME")
        if LooseVersion(self.version) < LooseVersion("2020"):
            cmd = "cd %s/MaterialsStudio* && %s ./install" % (self.builddir, self.cfg['preinstallopts'])
            qanda = {
                "The location where Materials Studio will be installed is <install location>/MaterialsStudio18.1 [%s/BIOVIA]" % home: self.installdir,
                "Please enter the location of a License Pack installation, or an empty directory into which the License Pack will be installed. [%s]" % self.installdir: self.installdir,
                "%s does not appear to contain a supported License Pack installation. Would you like to install it to that location? [Y/n] [Y]" % self.installdir: 'Y',
                "Would you like to specify an alternative Gateway port number (default is 18888) [N]": 'N',
                "Do you wish to start the Gateway service after installation? Answer no here if you wish to configure security settings before starting. (Y/n) [Y]": 'N',
                "Do you want to change the installation directory? (Y/N/Quit)": 'Y',
                "To select/deselect type its number: [1] Yes [2] No [3] Cancel >>>[1]": '1',
                "[ ] 0. Continue >>>": '0',
                " 1) Enter temporary license password 2) Set connection to license server 3) List command line license administration tools 99) Finished with license configuration Choose one of the above options:": '99'
            }
            no_qa = [ "Running installation ...", "Running ConfigureMaterialsStudio.pl" ]
            run_cmd_qa(cmd, qanda, no_qa = no_qa, log_all=True)
        else:
            cmd = 'cd %s/MaterialsStudio* && ./LicensePack/lp_setup_linux.sh --nox11 --target %s/tmp -- -silent -P "licensepack.installLocation=%s"' % (self.builddir, self.builddir, self.installdir)
            (out, _) = run_cmd(cmd, log_all=True, simple=False)

            cmd = "cd %s/MaterialsStudio* && %s ./install --batch --nonroot --nostart --installroot=%s --lproot=%s" % (self.builddir, self.cfg['preinstallopts'], self.installdir, self.installdir)
            (out, _) = run_cmd(cmd, log_all=True, simple=False)

        cmd = "echo %s >> %s/BIOVIA_LicensePack/Licenses/msi_server.fil" % (license_server, self.installdir)
        run_cmd(cmd, log_all=True)

    def sanity_check_step(self):
        """Custom sanity check for MaterialsStudio."""
        subdir = glob.glob(os.path.join(self.installdir,'MaterialsStudio*'))
        subdir = subdir[0]
        custom_paths = {
            'files': [os.path.join(subdir,'bin/dmol3.exe'), os.path.join(subdir,'etc/DMol3/bin/RunDMol3.sh')],
            'dirs': ['BIOVIA_LicensePack', os.path.join(subdir,'lib')],
        }

        super(EB_MaterialsStudio, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Add various bin folders of Materials Studio to the module"""
        txt = super(EB_MaterialsStudio, self).make_module_extra()

        subdirbins = glob.glob(os.path.join(self.installdir, 'MaterialsStudio*/bin'))
        subdirbins = subdirbins + glob.glob(os.path.join(self.installdir, 'MaterialsStudio*/etc/*/bin'))
        for d in subdirbins:
            txt += self.module_generator.prepend_paths('PATH', os.path.relpath(d,self.installdir))
        return txt

