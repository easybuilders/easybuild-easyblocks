##
# Copyright 2017 Bart Oldeman
#
# This file is triple-licensed under GPLv2 (see below), MIT, and
# BSD three-clause licenses.
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
General EasyBuild support for software, using nix to compile and install 

@author: Bart Oldeman (McGill University, Calcul Quebec, Compute Canada)
"""

from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.run import run_cmd


class Nix(EasyBlock):
    """
    Support for installing software via Nix
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to Binary easyblock."""
        extra_vars = EasyBlock.extra_options(extra_vars)
        extra_vars.update({
            'nix_attribute': [None, "Nix attribute name.", CUSTOM],
            'nix_profile': [None, "Nix profile to install to.", CUSTOM],
            'nix_cmd': [None, "Nix command to use.", CUSTOM],
        })
        return extra_vars

    def configure_step(self):
        """No configuration, included in nix"""
        pass

    def build_step(self):
        """Compilation done in install step"""
        pass

    def install_step(self):
        """Copy all files in build directory to the install directory"""
        if self.cfg['nix_attribute']:
            cmd = "/bin/sudo -u nixuser -i nix-env -iA %s -p %s" % (self.cfg['nix_attribute'], self.cfg['nix_profile'])
        else:
            cmd = "%s -p %s" % (self.cfg['nix_cmd'], self.cfg['nix_profile'])

        (out, _) = run_cmd(cmd, log_all=True, simple=False)
        return out

    def make_devel_module(self, create_in_builddir=False):
        """
        Make sure the easybuild directory is created in easybuild space
        """
        newinstalldir = self.installdir
        self.installdir = self.orig_installdir
        res = super(Nix, self).make_devel_module(create_in_builddir)
        self.installdir = newinstalldir
        return res
    
    def make_module_step(self, fake=False):
        """
        Custom module step for Nix: use Nix profile directly.
        """
        # For module file generation: temporarly set Nix profile
        self.orig_installdir = self.installdir
        if self.cfg['nix_profile'] is not None:
            self.installdir = self.cfg['nix_profile']

        # Generate module
        res = super(Nix, self).make_module_step(fake=fake)

        # Reset installdir to EasyBuild values
        self.installdir = self.orig_installdir
        return res

    def sanity_check_step(self):
        """
        Custom sanity check step for Nix: check in Nix profile
        """
        # For module file generation: temporarly set Nix profile
        orig_installdir = self.installdir
        if self.cfg['nix_profile'] is not None:
            self.installdir = self.cfg['nix_profile']

        # sanity check
        res = super(Nix, self).sanity_check_step()

        # Reset installdir to EasyBuild values
        self.installdir = orig_installdir
        return res

    
