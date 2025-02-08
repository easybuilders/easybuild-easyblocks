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
EasyBuild support for Perl module, implemented as an easyblock

@author: Jens Timmerman (Ghent University)
@author: Kenneth Hoste (Ghent University)
"""
import os

from easybuild.easyblocks.perl import EXTS_FILTER_PERL_MODULES, get_major_perl_version, get_site_suffix
from easybuild.framework.easyconfig import CUSTOM
from easybuild.framework.extensioneasyblock import ExtensionEasyBlock
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.environment import unset_env_vars


class PerlModule(ExtensionEasyBlock, ConfigureMake):
    """Builds and installs a Perl module, and can provide a dedicated module file."""

    @staticmethod
    def extra_options():
        """Easyconfig parameters specific to Perl modules."""
        extra_vars = {
            'runtest': ['test', "Run unit tests.", CUSTOM],  # overrides default
            'prefix_opt': [None, "String to use for option to set installation prefix (default is 'PREFIX')", CUSTOM],
        }
        return ExtensionEasyBlock.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialize custom class variables."""
        super(PerlModule, self).__init__(*args, **kwargs)
        self.testcmd = None

        # Environment variables PERL_MM_OPT and PERL_MB_OPT cause installations to fail.
        # Therefore it is better to unset these variables.
        unset_env_vars(['PERL_MM_OPT', 'PERL_MB_OPT'])

    def install_perl_module(self):
        """Install procedure for Perl modules: using either Makefile.Pl or Build.PL."""

        prefix_opt = self.cfg.get('prefix_opt')

        # Perl modules have two possible installation procedures: using Makefile.PL and Build.PL
        # configure, build, test, install
        if os.path.exists('Makefile.PL'):

            if prefix_opt is None:
                prefix_opt = 'PREFIX'

            install_cmd = ' '.join([
                self.cfg['preconfigopts'],
                'perl',
                'Makefile.PL',
                '%s=%s' % (prefix_opt, self.installdir),
                self.cfg['configopts'],
            ])
            run_shell_cmd(install_cmd)

            ConfigureMake.build_step(self)
            ConfigureMake.test_step(self)
            ConfigureMake.install_step(self)

        elif os.path.exists('Build.PL'):

            if prefix_opt is None:
                prefix_opt = '--prefix'

            install_cmd = ' '.join([
                self.cfg['preconfigopts'],
                'perl',
                'Build.PL',
                prefix_opt,
                self.installdir,
                self.cfg['configopts'],
            ])
            run_shell_cmd(install_cmd)

            run_shell_cmd("%s perl Build build %s" % (self.cfg['prebuildopts'], self.cfg['buildopts']))

            runtest = self.cfg['runtest']
            if runtest:
                run_shell_cmd('%s perl Build %s %s' % (self.cfg['pretestopts'], runtest, self.cfg['testopts']))
            run_shell_cmd('%s perl Build install %s' % (self.cfg['preinstallopts'], self.cfg['installopts']))

    def install_extension(self):
        """Perform the actual Perl module build/installation procedure"""

        if not self.src:
            raise EasyBuildError("No source found for Perl module %s, required for installation. (src: %s)",
                                 self.name, self.src)
        ExtensionEasyBlock.install_extension(self, unpack_src=True)

        self.install_perl_module()

    def configure_step(self):
        """No separate configuration for Perl modules."""
        pass

    def build_step(self):
        """No separate build procedure for Perl modules."""
        pass

    def test_step(self):
        """No separate (standard) test procedure for Perl modules."""
        pass

    def install_step(self):
        """Run install procedure for Perl modules."""
        self.install_perl_module()

    def sanity_check_step(self, *args, **kwargs):
        """
        Custom sanity check for Perl modules
        """
        return ExtensionEasyBlock.sanity_check_step(self, EXTS_FILTER_PERL_MODULES, *args, **kwargs)

    def make_module_step(self, *args, **kwargs):
        """
        Custom paths to look for with PERL*LIB
        """
        perl_lib_var = f"PERL{get_major_perl_version()}LIB"
        sitearchsuffix = get_site_suffix('sitearch')
        sitelibsuffix = get_site_suffix('sitelib')
        setattr(self.module_load_environment, perl_lib_var, ['', sitearchsuffix, sitelibsuffix])

        return super().make_module_step(*args, **kwargs)
