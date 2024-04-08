##
# Copyright 2022-2024 Vrije Universiteit Brussel
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
EasyBuild support for bundles of Julia packages, implemented as an easyblock

@author: Alex Domingo (Vrije Universiteit Brussel)
"""
import os

from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.easyblocks.generic.juliapackage import EXTS_FILTER_JULIA_PACKAGES, JuliaPackage
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root


class JuliaBundle(Bundle):
    """
    Bundle of JuliaPackages: install Julia packages as extensions in a bundle
    Defines custom sanity checks and module environment
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Easyconfig parameters specific to bundles of Julia packages."""
        if extra_vars is None:
            extra_vars = {}
        # combine custom easyconfig parameters of Bundle & JuliaPackage
        extra_vars = Bundle.extra_options(extra_vars)
        return JuliaPackage.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialize JuliaBundle easyblock."""
        super(JuliaBundle, self).__init__(*args, **kwargs)

        self.cfg['exts_defaultclass'] = 'JuliaPackage'
        self.cfg['exts_filter'] = EXTS_FILTER_JULIA_PACKAGES

        # need to disable templating to ensure that actual value for exts_default_options is updated...
        with self.cfg.disable_templating():
            # set default options for extensions according to relevant top-level easyconfig parameters
            jlpkg_keys = JuliaPackage.extra_options().keys()
            for key in jlpkg_keys:
                if key not in self.cfg['exts_default_options']:
                    self.cfg['exts_default_options'][key] = self.cfg[key]

            # Sources of Julia packages are commonly distributed from GitHub repos.
            # By default, rename downloaded tarballs to avoid name collisions on
            # packages sharing the same version string
            if 'sources' not in self.cfg['exts_default_options']:
                self.cfg['exts_default_options']['sources'] = [
                    {
                        'download_filename': 'v%(version)s.tar.gz',
                        'filename': '%(name)s-%(version)s.tar.gz',
                    }
                ]

        self.log.info("exts_default_options: %s", self.cfg['exts_default_options'])

    def prepare_step(self, *args, **kwargs):
        """Prepare for installing bundle of Julia packages."""
        super(JuliaBundle, self).prepare_step(*args, **kwargs)

        if get_software_root('Julia') is None:
            raise EasyBuildError("Julia not included as dependency!")

    def make_module_extra(self, *args, **kwargs):
        """
        Module has to append installation directory to JULIA_DEPOT_PATH to keep
        the user depot in the top entry. See issue easybuilders/easybuild-easyconfigs#17455
        """
        txt = super(JuliaBundle, self).make_module_extra()
        txt += self.module_generator.append_paths('JULIA_DEPOT_PATH', [''])
        return txt

    def sanity_check_step(self, *args, **kwargs):
        """Custom sanity check for bundle of Julia packages"""
        custom_paths = {
            'files': [],
            'dirs': [os.path.join('packages', self.name)],
        }
        super(JuliaBundle, self).sanity_check_step(custom_paths=custom_paths)
