# #
# Copyright 2013 Ghent University
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
# #
"""
EasyBuild support for installing Intel VTune, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""

from easybuild.easyblocks.generic.intelbase import IntelBase


class EB_VTune(IntelBase):
    """
    Support for installing Intel VTune
    """
    def make_module_req_guess(self):
        """
        A dictionary of possible directories to look for
        """

        guesses = super(EB_VTune, self).make_module_req_guess()

        if self.cfg['m32']:
            guesses.update({
                'PATH': ['bin32'],
                'LD_LIBRARY_PATH': ['lib32'],
                'LIBRARY_PATH': ['lib32'],
            })
        else:
            guesses.update({
                'PATH': ['bin64'],
                'LD_LIBRARY_PATH': ['lib64'],
                'LIBRARY_PATH': ['lib64'],
            })

        guesses.update({
            'CPATH': ['include'],
            'FPATH': ['include'],
            'MANPATH': ['man'],
        })

        return guesses

    def make_module_extra(self):
        """Custom variable definitions in module file."""
        
        txt = super(EB_VTune, self).make_module_extra()
        txt += self.moduleGenerator.prepend_paths('INTEL_LICENSE_FILE', self.license_file, allow_abs=True)

        return txt

    def sanity_check_step(self):
        """Custom sanity check paths for Intel VTune."""

        binaries = ['amplxe-cl', 'amplxe-configurator', 'amplxe-feedback', 'amplxe-gui', 'amplxe-runss']
        if self.cfg['m32']:
            files = ["bin32/%s" % x for x in binaries]
            dirs = ["lib32", "include"]
        else:
            files = ["bin64/%s" % x for x in binaries]
            dirs = ["lib64", "include"]

        custom_paths = {
                        'files': files,
                        'dirs': dirs,
                       }

        super(EB_VTune, self).sanity_check_step(custom_paths=custom_paths)
