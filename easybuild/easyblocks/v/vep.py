##
# Copyright 2009-2018 Ghent University
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
EasyBuild support for building and installing VEP, implemented as an easyblock
"""
import os

import easybuild.tools.environment as env
from easybuild.easyblocks.perl import get_major_perl_version
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.filetools import apply_regex_substitutions
from easybuild.tools.run import run_cmd


class EB_VEP(EasyBlock):
    """Support for building/installing VEP."""

    def __init__(self, *args, **kwargs):
        """VEP easyblock constructor."""
        super(EB_VEP, self).__init__(*args, **kwargs)

        self.build_in_installdir = True
        self.cfg['unpack_options'] = "--strip-components=1"

        self.api_mods_subdir = os.path.join('modules', 'api')

    def configure_step(self):
        """No custom configuration procedure for VEP."""
        pass

    def build_step(self):
        """No custom build procedure for VEP."""
        pass

    def install_step(self):
        """Custom install procedure for VEP."""

        # patch INSTALL.pl script to use https:// rather than ftp://
        apply_regex_substitutions('INSTALL.pl', [('ftp://', 'https://')])

        # update PERL5LIB so tests can run (done automatically by INSTALL.pl unless --NO_TEST is used)
        perl_majver = get_major_perl_version()
        perllib_envvar = 'PERL%sLIB' % perl_majver
        perllib = os.getenv(perllib_envvar, '')
        api_mods_dir = os.path.join(self.installdir, self.api_mods_subdir)
        self.log.info("Adding %s to $%s (%s)", api_mods_dir, perllib_envvar, perllib)
        env.setvar(perllib_envvar, '%s:%s' % (api_mods_dir, perllib))

        # see https://www.ensembl.org/info/docs/tools/vep/script/vep_download.html#installer
        cmd = ' '.join([
            self.cfg['preinstallopts'],
            'perl',
            'INSTALL.pl',
            # don't try to install optional Bio::DB::HTS (can be provided as an extension instead)
            '--NO_HTSLIB',
            # a: API, f: FASTA
            # not included:
            # c: cache, should be downloaded by user
            # l: Bio::DB::HTS, should be provided via EasyBuild
            # p: plugins
            '--AUTO af',
            # install all species
            '--SPECIES all',
            # don't update VEP during installation
            '--NO_UPDATE',
            # location to install Perl API modules into
            '--DESTDIR ' + api_mods_dir,
            self.cfg['installopts'],
        ])
        run_cmd(cmd, log_all=True, simple=True, log_ok=True)

    def sanity_check_step(self):
        """Custom sanity check for VEP."""
        custom_paths = {
            'files': ['vep'],
            'dirs': ['modules/Bio/EnsEMBL/VEP'],
        }
        custom_commands = ['vep --help']

        super(EB_VEP, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_req_guess(self):
        """Custom guesses for environment variables (PATH, ...) for VEP."""
        perl_majver = get_major_perl_version()

        guesses = super(EB_VEP, self).make_module_req_guess()
        guesses = {
            'PATH': '',
            'PERL%sLIB' % perl_majver: self.api_mods_subdir,
        }
        return guesses
