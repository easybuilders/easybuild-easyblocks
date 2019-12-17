##
# Copyright 2009-2019 Ghent University
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
EasyBuild support for Perl, implemented as an easyblock

@author: Jens Timmerman (Ghent University)
@author: Kenneth Hoste (Ghent University)
"""
import os

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.py2vs3 import string_type
from easybuild.tools.run import run_cmd

# perldoc -lm seems to be the safest way to test if a module is available, based on exit code
EXTS_FILTER_PERL_MODULES = ("perldoc -lm %(ext_name)s ", "")


class EB_Perl(ConfigureMake):
    """Support for building and installing Perl."""

    @staticmethod
    def extra_options():
        """Add extra config options specific to Perl."""
        extra_vars = {
            'use_perl_threads': [True, "Enable use of internal Perl threads via -Dusethreads configure option", CUSTOM],
        }
        return ConfigureMake.extra_options(extra_vars)

    def configure_step(self):
        """
        Configure Perl build: run ./Configure instead of ./configure with some different options
        """
        # avoid that $CPATH or $C_INCLUDE_PATH include an empty entry, since that makes Perl build fail miserably
        # see https://github.com/easybuilders/easybuild-easyconfigs/issues/8859
        for key in ['CPATH', 'C_INCLUDE_PATH']:
            value = os.getenv(key, None)
            if value is not None:
                paths = value.split(os.pathsep)
                if '' in paths:
                    self.log.info("Found empty entry in $%s, filtering it out...", key)
                    os.environ[key] = os.pathsep.join(p for p in paths if p)

        majver = self.version.split('.')[0]
        configopts = [
            self.cfg['configopts'],
            '-Dcc="{0}"'.format(os.getenv('CC')),
            '-Dccflags="{0}"'.format(os.getenv('CFLAGS')),
            '-Dinc_version_list=none',
            '-Dprefix=%(installdir)s',
            # guarantee that scripts are installed in /bin in the installation directory (and not in a guessed path)
            # see https://github.com/easybuilders/easybuild-easyblocks/issues/1659
            '-Dinstallscript=%(installdir)s/bin',
            '-Dscriptdir=%(installdir)s/bin',
            '-Dscriptdirexp=%(installdir)s/bin',
            # guarantee that the install directory has the form lib/perlX/
            # see https://github.com/easybuilders/easybuild-easyblocks/issues/1700
            "-Dinstallstyle='lib/perl%s'" % majver,
        ]
        if self.cfg['use_perl_threads']:
            configopts.append('-Dusethreads')

        configopts = (' '.join(configopts)) % {'installdir': self.installdir}

        cmd = './Configure -de %s' % configopts
        run_cmd(cmd, log_all=True, simple=True)

    def test_step(self):
        """Test Perl build via 'make test'."""
        # allow escaping with runtest = False
        if self.cfg['runtest'] is None or self.cfg['runtest']:
            if isinstance(self.cfg['runtest'], string_type):
                cmd = "make %s" % self.cfg['runtest']
            else:
                cmd = "make test"

            # specify locale to be used, to avoid that a handful of tests fail
            cmd = "export LC_ALL=C && %s" % cmd

            run_cmd(cmd, log_all=False, log_ok=False, simple=False)

    def prepare_for_extensions(self):
        """
        Set default class and filter for Perl modules
        """
        # build and install additional modules with PerlModule easyblock
        self.cfg['exts_defaultclass'] = "PerlModule"
        self.cfg['exts_filter'] = EXTS_FILTER_PERL_MODULES

    def sanity_check_step(self):
        """Custom sanity check for Perl."""
        majver = self.version.split('.')[0]
        custom_paths = {
            'files': [os.path.join('bin', x) for x in ['perl', 'perldoc']],
            'dirs': ['lib/perl%s/%s' % (majver, self.version), 'man']
        }
        super(EB_Perl, self).sanity_check_step(custom_paths=custom_paths)


def get_major_perl_version():
    """"
    Returns the major verson of the perl binary in the current path
    """
    cmd = "perl -MConfig -e 'print $Config::Config{PERL_API_REVISION}'"
    (perlmajver, _) = run_cmd(cmd, log_all=True, log_output=True, simple=False)
    return perlmajver


def get_site_suffix(tag):
    """
    Returns the suffix for site* (e.g. sitearch, sitelib)
    this will look something like /lib/perl5/site_perl/5.16.3/x86_64-linux-thread-multi
    so, e.g. sitearch without site prefix

    @tag: site tag to use, e.g. 'sitearch', 'sitelib'
    """
    perl_cmd = 'my $a = $Config::Config{"%s"}; $a =~ s/($Config::Config{"siteprefix"})//; print $a' % tag
    cmd = "perl -MConfig -e '%s'" % perl_cmd
    (sitesuffix, _) = run_cmd(cmd, log_all=True, log_output=True, simple=False)
    # obtained value usually contains leading '/', so strip it off
    return sitesuffix.lstrip(os.path.sep)
