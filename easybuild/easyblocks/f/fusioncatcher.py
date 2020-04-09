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
EasyBuild support for building and installing FusionCatcher

@author: Pavel Grochal (INUITS)
"""
import os

from easybuild.easyblocks.generic.tarball import Tarball
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.filetools import apply_regex_substitutions
from easybuild.tools.modules import get_software_root, get_software_version


class EB_FusionCatcher(Tarball):
    """Support for building/installing FusionCatcher."""

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for FusionCather."""
        extra_vars = {
            'seqtk_bundled': [False, "Denotes if seqtk is installed in bundle or as separate EasyConfig", CUSTOM],
         }
        return Tarball.extra_options(extra_vars)

    def install_step(self, *args, **kwargs):
        """
        Custom install step for FusionCatcher.

        replaces paths in configuration.cfg file to link installed versions via EB
        fixes hardcoded version requirements
        """
        super(EB_FusionCatcher, self).install_step(*args, **kwargs)

        # path to FusionCatcher configuration file
        fusioncatcher_config_file = os.path.join(self.installdir, 'etc', 'configuration.cfg')

        # replace incorrect paths for some bin executables
        regex_subs = [
            (r'\r\n', r'\n'),   # CRLF :(
            (r'(python = ).*', r'\1%s' % os.path.join(get_software_root('Python'), 'bin')),
            (r'(scripts = ).*', r'\1%s' % os.path.join(self.installdir, 'bin')),
            (r'(java = ).*', r'\1%s' % os.path.join(get_software_root('Java'), 'bin')),
        ]

        # replace path for following modules
        link_sw = [
            ('bowtie', 'Bowtie'),
            ('bowtie2', 'Bowtie2'),
            ('blat', 'BLAT'),
            ('bbmap', 'BBMap'),
            ('liftover', 'liftOver'),
            ('fatotwobit', 'faToTwoBit'),
            ('star', 'STAR'),
            ('sra', 'SRA-Toolkit'),
            ('numpy', 'SciPy-bundle'),
            ('biopython', 'Biopython'),
            ('pigz', 'pigz'),
            ('picard', 'picard'),
        ]
        # current FusionCather (1.20) needs specific seqtk version from specific fork (https://github.com/ndaniel/seqtk)
        # if this is included in Bundle, seqtk PATH shouldn't be changed in configuration file.
        if not self.cfg['seqtk_bundled']:
            link_sw += [('seqtk', 'seqtk')]

        # replace incorrect paths for modules
        regex_subs += [(r'(%s = ).*' % name, r'\1%s' % get_software_root(module)) for name, module in link_sw]

        apply_regex_substitutions(fusioncatcher_config_file, regex_subs)

        # fix hardcoded version checks. It works with other versions as well (currently except for seqtk)
        fusioncatcher_py_file = os.path.join(self.installdir, 'bin', 'fusioncatcher.py')
        regex_subs_fusion = [
            ('bbmap version 38.44', 'bbmap version %s' % get_software_version('BBMap')),
            ("correct_version = '2.7.2b'", "correct_version = '%s'" % get_software_version('STAR')),
        ]
        apply_regex_substitutions(fusioncatcher_py_file, regex_subs_fusion)

    def sanity_check_step(self):
        """Custom sanity check for FusionCatcher"""
        custom_paths = {
            'files': [os.path.join('bin', 'fusioncather.py'), os.path.join('etc', 'configuration.cfg')],
            'dirs': [],
        }
        custom_commands = ['fusioncather.py -h']
        super(EB_FusionCatcher, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
