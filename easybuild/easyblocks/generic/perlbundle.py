##
# Copyright 2018-2024 Ghent University
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
EasyBuild support for installing a bundle of Perl modules, implemented as a generic easyblock

@author: Mikael Oehman (Chalmers University of Technology)
"""
import os

from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.easyblocks.generic.perlmodule import PerlModule
from easybuild.easyblocks.perl import get_major_perl_version, get_site_suffix
from easybuild.tools.config import build_option
from easybuild.tools.environment import setvar


class PerlBundle(Bundle):
    """
    Bundle of perl modules
    """

    @staticmethod
    def extra_options():
        """Easyconfig parameters specific to bundles of Perl modules."""
        # combine custom easyconfig parameters of Bundle & PerlModule
        extra_vars = PerlModule.extra_options()
        return Bundle.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialize PerlBundle easyblock."""
        super(PerlBundle, self).__init__(*args, **kwargs)

        self.cfg['exts_defaultclass'] = 'PerlModule'
        self.cfg['exts_filter'] = ("perl -e 'require %(ext_name)s'", '')

    def extensions_step(self, *args, **kwargs):
        """Install extensions"""

        setvar('INSTALLDIRS', 'site')
        # define $OPENSSL_PREFIX to ensure that e.g. Net-SSLeay extension picks up OpenSSL
        # from specified sysroot rather than from host OS
        sysroot = build_option('sysroot')
        if sysroot:
            setvar('OPENSSL_PREFIX', sysroot)

        super(PerlBundle, self).extensions_step(*args, **kwargs)

    def test_step(self):
        """No global test step for bundle of Perl modules."""
        # required since runtest is set to True by default
        pass

    def sanity_check_step(self, *args, **kwargs):
        """Custom sanity check for bundle of Perl modules."""

        if not self.cfg['sanity_check_paths']:
            majver = get_major_perl_version()
            self.cfg['sanity_check_paths'] = {
                'files': [],
                'dirs': [os.path.join('lib', 'perl%s' % majver)],
            }

        super(Bundle, self).sanity_check_step(*args, **kwargs)

    def make_module_extra(self):
        """Extra module entries for Perl bundles."""
        majver = get_major_perl_version()
        sitelibsuffix = get_site_suffix('sitelib')

        txt = super(Bundle, self).make_module_extra()
        txt += self.module_generator.prepend_paths("PERL%sLIB" % majver, [sitelibsuffix])
        return txt
