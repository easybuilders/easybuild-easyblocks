##
# Copyright 2009-2025 Ghent University
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
EasyBuild support for building and installing RepeatMasker, implemented as an easyblock
"""
from easybuild.tools import LooseVersion
import os

from easybuild.easyblocks.generic.tarball import Tarball
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import change_dir, patch_perl_script_autoflush
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_shell_cmd


class EB_RepeatMasker(Tarball):
    """Support for building/installing RepeatMasker."""

    def __init__(self, *args, **kwargs):
        """Easyblock constructor."""
        super(EB_RepeatMasker, self).__init__(*args, **kwargs)

        # custom path-like environment variables for RepeatMaskerConfig
        self.module_load_environment.PATH = ['']

    def install_step(self):
        """Custom install procedure for RepeatMasker."""
        super(EB_RepeatMasker, self).install_step()

        # check for required dependencies
        perl_root = get_software_root('Perl')
        if perl_root:
            perl = os.path.join(perl_root, 'bin', 'perl')
        else:
            raise EasyBuildError("Missing required dependency: Perl")

        trf_root = get_software_root('TRF')
        if trf_root:
            trf = os.path.join(trf_root, 'trf')
        else:
            raise EasyBuildError("Missing required dependency: TRF")

        # determine which search engine to use
        # see also http://www.repeatmasker.org/RMDownload.html
        cand_search_engines = ['CrossMatch', 'RMBlast', 'WUBlast', 'HMMER']
        search_engine = None
        for dep in cand_search_engines:
            if get_software_root(dep):
                if search_engine is None:
                    search_engine = dep
                else:
                    raise EasyBuildError("Found multiple candidate search engines: %s and %s", search_engine, dep)

        if search_engine is None:
            raise EasyBuildError("No search engine found, one of these must be included as dependency: %s",
                                 ' '.join(cand_search_engines))

        change_dir(self.installdir)

        patch_perl_script_autoflush('configure')

        search_engine_bindir = os.path.join(get_software_root(search_engine), 'bin')

        if LooseVersion(self.version) >= LooseVersion('4.0.9'):
            search_engine_map = {
                'CrossMatch': '1',
                'RMBlast': '2',
                'HMMER': '3',
                'WUBlast': '4',
            }
            qa = [
                (r'\*\*TRF PROGRAM\*\*\n\n.*\n.*\n+Enter path.*', trf),
                (r'.*\[ Un\-configured \]\n.*\[ Un\-configured \]\n.*\[ Un\-configured \]\n'
                 r'.*\[ Un\-configured \]\n\n.*\n\n\nEnter Selection:\s*', search_engine_map[search_engine]),
                (r'\*\*.* INSTALLATION PATH\*\*\n\n.*\n.*\n+Enter path.*', search_engine_bindir),
                (r'search engine for Repeatmasker.*', 'Y'),
                (r'.*\[ Configured, Default \](.*\n)*\n\nEnter Selection:\s*', '5'),  # 'Done'
            ]
        else:
            search_engine_map = {
                'CrossMatch': '1',
                'RMBlast': '2',
                'WUBlast': '3',
                'HMMER': '4',
            }
            qa = [
                (r'<PRESS ENTER TO CONTINUE>', ''),
                # select search engine
                (r'Enter Selection:', search_engine_map[search_engine]),
                (r'\*\*PERL PROGRAM\*\*\n([^*]*\n)+Enter path.*', perl),
                (r'\*\*REPEATMASKER INSTALLATION DIRECTORY\*\*\n([^*]*\n)+Enter path.*', self.installdir),
                (r'\*\*TRF PROGRAM\*\*\n([^*]*\n)+Enter path.*', trf),
                # search engine installation path (location of /bin subdirectory)
                # also enter 'Y' to confirm + '5' ("Done") to complete selection process for search engine
                (r'\*\*.* INSTALLATION PATH\*\*\n([^*]*\n)+Enter path.*', search_engine_bindir + '\nY\n5'),
            ]

        cmd = "perl ./configure"
        run_shell_cmd(cmd, qa_patterns=qa, qa_timeout=300)

    def sanity_check_step(self):
        """Custom sanity check for RepeatMasker."""

        custom_paths = {
            'files': ['RepeatMasker', 'RepeatMaskerConfig.pm'],
            'dirs': ['Libraries', 'util'],
        }

        custom_commands = ['RepeatMasker']

        super(EB_RepeatMasker, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
