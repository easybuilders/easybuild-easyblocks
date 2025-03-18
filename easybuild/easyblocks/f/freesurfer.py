##
# Copyright 2013-2025 Ghent University
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
EasyBuild support for building and installing FreeSurfer, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""

import os

from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.tarball import Tarball
from easybuild.framework.easyconfig import MANDATORY
from easybuild.tools.filetools import write_file


class EB_FreeSurfer(Tarball):
    """Support for building and installing FreeSurfer."""

    @staticmethod
    def extra_options():
        extra_vars = {
            'license_text': ['', "Text for required license file.", MANDATORY],
        }
        return Tarball.extra_options(extra_vars)

    def install_step(self):
        """Custom installation procedure for FreeSurfer, which includes installed the license file '.license'."""
        super(EB_FreeSurfer, self).install_step()
        write_file(os.path.join(self.installdir, '.license'), self.cfg['license_text'])

    def __init__(self, *args, **kwargs):
        """Custom constructor for FLUENT easyblock, initialize/define class parameters."""
        super(EB_FreeSurfer, self).__init__(*args, **kwargs)

        self.module_load_environment.PATH.extend([
            os.path.join('fsfast', 'bin'),
            os.path.join('mni', 'bin'), 'tktools',
        ])

    def make_module_extra(self):
        """Define FreeSurfer-specific environment variable in generated module file."""
        txt = super(EB_FreeSurfer, self).make_module_extra()

        freesurfer_vars = {
            'FMRI_ANALYSIS_DIR': os.path.join(self.installdir, 'fsfast'),
            'FS_OVERRIDE': '0',
            'FSF_OUTPUT_FORMAT': 'nii.gz',
            'FSFAST_HOME': os.path.join(self.installdir, 'fsfast'),
            'FREESURFER': self.installdir,
            'FREESURFER_HOME': self.installdir,
            'FUNCTIONALS_DIR': os.path.join(self.installdir, 'sessions'),
            'MNI_DIR': os.path.join(self.installdir, 'mni'),
            'MNI_DATAPATH': os.path.join(self.installdir, 'mni', 'data'),
            'MINC_BIN_DIR': os.path.join(self.installdir, 'mni', 'bin'),
            'MINC_LIB_DIR': os.path.join(self.installdir, 'mni', 'lib'),
            'MNI_PERL5LIB': os.path.join(self.installdir, 'mni', 'lib', 'perl5', '5.8.5'),
            'PERL5LIB': os.path.join(self.installdir, 'mni', 'lib', 'perl5', '5.8.5'),
            'OS': 'linux',
            'SUBJECTS_DIR': os.path.join(self.installdir, 'subjects'),
        }

        for key, value in sorted(freesurfer_vars.items()):
            txt += self.module_generator.set_environment(key, freesurfer_vars[key])

        return txt

    def sanity_check_step(self):
        """Custom sanity check for FreeSurfer"""
        custom_paths = {
            'files': ['FreeSurferEnv.sh', '.license'],
            'dirs': ['bin', 'lib', 'mni'],
        }

        custom_commands = []
        if LooseVersion(self.version) >= LooseVersion("7.2"):
            custom_commands.append('checkMCR.sh')

        super(EB_FreeSurfer, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
