##
# This file is an EasyBuild reciPY as per https://github.com/hpcugent/easybuild
#
# Copyright:: Copyright 2012-2015 Uni.Lu/LCSB, NTUA
# Authors::   Fotis Georgatos <fotis@cern.ch>
# License::   MIT/GPL
# $Id$
#
# This work implements a part of the HPCBIOS project and is a component of the policy:
# http://hpcbios.readthedocs.org/en/latest/HPCBIOS_06-05.html
##
"""
EasyBuild support for installing Totalview, implemented as an easyblock

@author: Fotis Georgatos (Uni.Lu)
"""
import os

from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd


class EB_TotalView(EasyBlock):
    """EasyBlock for TotalView"""

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for Totalview"""
        super(EB_TotalView, self).__init__(*args, **kwargs)
        if not self.cfg['license_file']:
            self.cfg['license_file'] = 'UNKNOWN'

    def configure_step(self):
        """No configuration for TotalView."""
        if not os.path.exists(self.cfg['license_file']):
            raise EasyBuildError("Non-existing license file specified: %s", self.cfg['license_file'])

    def build_step(self):
        """No building for TotalView."""
        pass

    def install_step(self):
        """Custom install procedure for TotalView."""

        cmd = "./Install -agree -platform linux-x86-64 -nosymlink -install totalview -directory %s" % self.installdir
        run_cmd(cmd)

    def sanity_check_step(self):
        """Custom sanity check for TotalView."""

        binpath_t = 'toolworks/%s.%s/bin/' % (self.name.lower(), self.version) + 'tv%s'

        custom_paths = {
            'files': [binpath_t % i for i in ['8', '8cli', 'dbootstrap', 'dsvr', 'script']],
            'dirs': [],
        }

        super(EB_TotalView, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_req_guess(self):
        """Specify TotalView custom values for PATH."""
        guesses = super(EB_TotalView, self).make_module_req_guess()

        prefix = os.path.join('toolworks', '%s.%s' % (self.name.lower(), self.version))
        guesses.update({
            'PATH': [os.path.join(prefix, 'bin')],
            'MANPATH': [os.path.join(prefix, 'man')],
        })

        return guesses

    def make_module_extra(self):
        """Add extra environment variables for license file and anything else."""
        txt = super(EB_TotalView, self).make_module_extra()
        txt += self.module_generator.prepend_paths('LM_LICENSE_FILE', [self.cfg['license_file']], allow_abs=True)
        return txt
