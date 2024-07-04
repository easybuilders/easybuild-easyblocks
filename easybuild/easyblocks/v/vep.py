##
# Copyright 2009-2024 Ghent University
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
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import print_warning
from easybuild.tools.filetools import apply_regex_substitutions
from easybuild.tools.modules import get_software_version, get_software_root
from easybuild.tools.run import run_cmd


class EB_VEP(EasyBlock):
    """Support for building/installing VEP."""

    def __init__(self, *args, **kwargs):
        """VEP easyblock constructor."""
        super(EB_VEP, self).__init__(*args, **kwargs)

        self.build_in_installdir = True
        self.cfg['unpack_options'] = "--strip-components=1"

        self.api_mods_subdir = os.path.join('modules', 'api')

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to VEP easyblock."""
        extra_vars = EasyBlock.extra_options(extra_vars)
        extra_vars.update({
            'species': ['all', "Comma-separated list of species to pass to INSTALL.pl", CUSTOM],
        })
        return extra_vars

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

        # check for bundled dependencies
        bundled_deps = [
            # tuple format: (package name in EB, option name for INSTALL.pl)
            ('BioPerl', 'NO_BIOPERL'),
            ('Bio-DB-HTS', 'NO_HTSLIB'),
        ]
        installopt_deps = []

        for (dep, opt) in bundled_deps:
            if get_software_root(dep):
                installopt_deps.append('--%s' % opt)

        installopt_deps = ' '.join(installopt_deps)

        # see https://www.ensembl.org/info/docs/tools/vep/script/vep_download.html#installer
        cmd = ' '.join([
            self.cfg['preinstallopts'],
            'perl',
            'INSTALL.pl',
            # disable installation of bundled dependencies that are provided as dependencies in the easyconfig
            installopt_deps,
            # a: API, f: FASTA
            # not included:
            # c: cache, should be downloaded by user
            # l: Bio::DB::HTS, should be provided via EasyBuild
            # p: plugins
            '--AUTO af',
            # install selected species
            '--SPECIES %s' % self.cfg['species'],
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

        if 'Bio::EnsEMBL::XS' in [ext[0] for ext in self.cfg['exts_list']]:
            # determine Perl version used as dependency;
            # take into account that Perl module may not be loaded, for example when --sanity-check-only is used
            perl_ver = None
            deps = self.cfg.dependencies()
            for dep in deps:
                if dep['name'] == 'Perl':
                    perl_ver = dep['version']
                    break

            if perl_ver is None:
                print_warning("Failed to determine version of Perl dependency!")
            else:
                perl_majver = perl_ver.split('.')[0]
                perl_libpath = os.path.join('lib', 'perl' + perl_majver, 'site_perl', perl_ver)
                bio_ensembl_xs_ext = os.path.join(perl_libpath, 'x86_64-linux-thread-multi', 'Bio', 'EnsEMBL', 'XS.pm')
                custom_paths['files'].extend([bio_ensembl_xs_ext])

        custom_commands = ['vep --help']

        super(EB_VEP, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_req_guess(self):
        """Custom guesses for environment variables (PATH, ...) for VEP."""
        perl_majver = get_major_perl_version()

        perl_libpath = [self.api_mods_subdir]
        if 'Bio::EnsEMBL::XS' in [ext[0] for ext in self.cfg['exts_list']]:
            perl_ver = get_software_version('Perl')
            perl_libpath.extend([os.path.join('lib', 'perl' + perl_majver, 'site_perl', perl_ver)])

        guesses = super(EB_VEP, self).make_module_req_guess()
        guesses = {
            'PATH': '',
            'PERL%sLIB' % perl_majver: perl_libpath,
        }
        return guesses
